"""음성인식 (faster-whisper). 결과는 transcript.json으로 저장해 다시 쓸 수 있습니다.

transcript 형식:
{"language": "ko", "duration": 3600.0, "segments": [
  {"id": 0, "start": 1.2, "end": 4.8, "text": "...", "words": [{"start": 1.2, "end": 1.6, "word": "안녕하세요"}, ...]}
]}
"""

import json
import wave
from pathlib import Path
from typing import Callable


def transcribe(
    audio: Path,
    offset: float = 0.0,
    model_size: str = "small",
    language: str = "ko",
    device: str = "cpu",
    on_progress: Callable[[float], None] | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    if device != "cpu":
        try:
            return _transcribe(audio, offset, model_size, language, device, on_progress)
        except Exception as e:  # GPU 라이브러리(cuBLAS/cuDNN)가 없으면 흔히 여기서 실패합니다
            log(f"\n  ⚠ GPU로 음성인식을 못 했어요 ({type(e).__name__}: {str(e)[:120]}) → CPU로 다시 합니다")
    return _transcribe(audio, offset, model_size, language, "cpu", on_progress)


def load_wav(path: Path):
    """ffmpeg로 뽑은 16kHz 모노 16비트 WAV → float32 배열.

    faster-whisper에 파일 경로를 주면 내부에서 PyAV로 읽는데, PyAV 최신판(15+)과
    호환이 깨져 'metadata_errors' 오류가 납니다. 그래서 직접 읽어 배열로 넘깁니다.
    """
    import numpy as np

    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getframerate() != 16000:
            raise ValueError(f"16kHz 모노 16비트 WAV가 아니에요: {path}")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def _transcribe(audio, offset, model_size, language, device, on_progress) -> dict:
    from faster_whisper import WhisperModel

    # CPU에서는 int8이 빠르고 품질 차이가 거의 없습니다.
    compute_type = "int8" if device == "cpu" else "default"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        load_wav(audio),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    out = []
    for seg in segments:  # 실제 인식은 여기서 하나씩 진행됩니다
        text = seg.text.strip()
        if not text:
            continue
        out.append({
            "id": len(out),
            "start": round(seg.start + offset, 3),
            "end": round(seg.end + offset, 3),
            "text": text,
            "words": [
                {"start": round(w.start + offset, 3), "end": round(w.end + offset, 3), "word": w.word.strip()}
                for w in (seg.words or [])
                if w.word.strip()
            ],
        })
        if on_progress and info.duration:
            on_progress(min(1.0, seg.end / info.duration))
    return {"language": info.language, "duration": info.duration, "offset": offset, "segments": out}


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    segs = data.get("segments")
    if not isinstance(segs, list):
        raise ValueError(f"transcript 형식이 아니에요: {path}")
    for i, s in enumerate(segs):
        s.setdefault("id", i)
        s.setdefault("words", [])
    return data


def save(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
