"""로컬 한국어 전사(faster-whisper). 외부 API 비용 없음(하드웨어·시간 비용은 있음).

결과는 원본 해시·엔진·모델·언어·설정 버전·사전으로 캐시한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from . import config, db, dictionary, jobs, media, services, subtitles
from .errors import StudioError

ENGINE = "faster-whisper"
SETTINGS_VERSION = "asr-v1"
LANGUAGE = "ko"


def engine_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def model_status() -> dict:
    name = config.WHISPER_MODEL or "small"
    if Path(name).exists():
        return {"model": name, "state": "local", "label": "로컬 모델 폴더 사용"}
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cache = hf_home / "hub" / f"models--Systran--faster-whisper-{name}"
    if cache.exists() and any(cache.rglob("model.bin")):
        return {"model": name, "state": "cached", "label": "다운로드된 모델 있음"}
    return {"model": name, "state": "download_required",
            "label": "첫 전사 때 Hugging Face에서 모델을 내려받습니다(인터넷 필요, 수백 MB~)."}


def status() -> dict:
    return {"engine": ENGINE, "installed": engine_installed(), "language": LANGUAGE, "device": config.WHISPER_DEVICE,
            "cost": "외부 API 요금 없음(로컬 CPU/GPU 사용)", **model_status()}


def cache_key(source_sha: str) -> str:
    raw = json.dumps([source_sha, ENGINE, config.WHISPER_MODEL, LANGUAGE, SETTINGS_VERSION, sorted(dictionary.words())], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _extract_audio(src: Path, out: Path, handle: media.ProcessHandle) -> None:
    ff, _ = media.require_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return
    tmp = out.with_suffix(".part.wav")
    cmd = [ff, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    handle.proc = proc
    _, err = proc.communicate()
    if handle.canceled.is_set():
        raise StudioError("CANCELED")
    if proc.returncode != 0:
        raise StudioError("MEDIA_INVALID", (err or b"").decode("utf-8", "replace")[-300:])
    tmp.replace(out)


def segments_to_cues(segments: list[dict]) -> list[dict]:
    cues = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        flags = dictionary.check_flags(text)
        words = seg.get("words") or []
        low = seg.get("avg_logprob", 0) < -1.0 or any(w.get("probability", 1) < 0.45 for w in words)
        if low:
            flags.append("low_conf")
        cues.append({"id": subtitles.new_cue_id(), "start_ms": int(round(seg["start"] * 1000)), "end_ms": int(round(seg["end"] * 1000)),
                     "text": text, "flags": flags, "conf": round(seg.get("avg_logprob", 0), 3),
                     "words": [{"w": w["word"], "s": int(round(w["start"] * 1000)), "e": int(round(w["end"] * 1000)),
                                "p": round(w.get("probability", 1), 3)} for w in words]})
    return cues


@jobs.register("transcribe")
def handle_transcribe(job: dict, ctx: jobs.JobContext) -> dict:
    project = services.get_project(job["project_id"])
    source = services.get_source(project["source_id"])
    if not source:
        raise StudioError("NOT_FOUND", "원본")
    key = cache_key(source["sha256"])
    force = bool((job.get("params") or {}).get("force"))
    cached = db.fetchone("SELECT * FROM transcribe_cache WHERE key=?", (key,))
    if cached and not force:
        tr = services.save_transcript(project["id"], cached["cues"], "asr", ENGINE, cached["model"])
        return {"cached": True, "transcript_id": tr["id"], "cues": len(cached["cues"])}
    if not engine_installed():
        raise StudioError("STT_NOT_INSTALLED")
    if not source["has_audio"]:
        raise StudioError("MEDIA_INVALID", "음성 트랙이 없습니다")
    ctx.progress(None, "음성 추출", force=True)
    wav = config.CACHE_DIR / "audio" / f"{source['sha256'][:32]}.wav"
    _extract_audio(Path(source["path"]), wav, ctx.handle)
    ctx.check_cancel()
    ctx.progress(None, "전사 모델 불러오는 중", force=True)
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE, compute_type=config.WHISPER_COMPUTE)
    except Exception as e:  # 모델 다운로드 실패·경로 오류
        raise StudioError("STT_MODEL_MISSING", config.redact(f"{type(e).__name__}: {str(e)[:300]}")) from e
    hot = " ".join(dictionary.words())
    seg_iter, info = model.transcribe(str(wav), language=LANGUAGE, word_timestamps=True, vad_filter=True,
                                      initial_prompt=hot or None, hotwords=hot or None)
    total = max(1.0, float(info.duration or (source["duration_ms"] / 1000)))
    segments = []
    for seg in seg_iter:
        ctx.check_cancel()
        segments.append({"start": seg.start, "end": seg.end, "text": seg.text, "avg_logprob": seg.avg_logprob,
                         "words": [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability} for w in (seg.words or [])]})
        ctx.progress(min(0.99, seg.end / total), f"전사 중 {int(seg.end)}/{int(total)}초")
    cues = segments_to_cues(segments)
    db.execute("INSERT INTO transcribe_cache(key, cues_json, engine, model, info_json, created_at) VALUES(?,?,?,?,?,?) "
               "ON CONFLICT(key) DO UPDATE SET cues_json=excluded.cues_json, created_at=excluded.created_at",
               (key, db.dumps(cues), ENGINE, config.WHISPER_MODEL, db.dumps({"language": info.language, "duration": info.duration}), db.now()))
    tr = services.save_transcript(project["id"], cues, "asr", ENGINE, config.WHISPER_MODEL)
    return {"cached": False, "transcript_id": tr["id"], "cues": len(cues)}
