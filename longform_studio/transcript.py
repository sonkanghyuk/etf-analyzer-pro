"""받아쓰기: faster-whisper(내 PC) 또는 기존 SRT/VTT → 단어 타임라인 → 문장."""
from __future__ import annotations

import json
import re
from pathlib import Path

TC = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def from_whisper(media: Path, model: str = "large-v3", prompt: str | None = None) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover - 환경 의존
        raise SystemExit("faster-whisper가 없습니다: pip install faster-whisper  (또는 --srt 로 자막 파일 지정)") from e
    try:
        m = WhisperModel(model, device="auto", compute_type="auto")
    except Exception:  # GPU 설정 실패 시 CPU
        m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(str(media), language="ko", word_timestamps=True, vad_filter=True,
                           initial_prompt=prompt, condition_on_previous_text=True)
    words = []
    for seg in segs:
        for w in seg.words or []:
            if w.word.strip():
                words.append({"s": round(w.start, 3), "e": round(w.end, 3), "w": w.word.strip()})
    return words


def from_subtitle_file(path: Path) -> list[dict]:
    """세그먼트 자막(SRT/VTT)을 어절 단위로 나눠 글자 수 비례로 시간 배분."""
    text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r", "")
    words = []
    for block in re.split(r"\n\s*\n", text):
        m = TC.search(block)
        if not m:
            continue
        s, e = _sec(*m.groups()[:4]), _sec(*m.groups()[4:])
        body = " ".join(ln.strip() for ln in block[m.end():].split("\n") if ln.strip())
        body = re.sub(r"<[^>]+>", "", body)
        toks = body.split()
        if not toks:
            continue
        total = sum(len(t) for t in toks)
        t = s
        for tok in toks:
            d = (e - s) * len(tok) / total
            words.append({"s": round(t, 3), "e": round(t + d, 3), "w": tok})
            t += d
        words[-1]["w"] = words[-1]["w"] if re.search(r"[.?!]$", words[-1]["w"]) else words[-1]["w"] + "."
    return words


def sentences(words: list[dict], gap: float = 0.9) -> list[list[dict]]:
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and w["s"] - cur[-1]["e"] > gap:
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.?!]$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def save(words: list[dict], ep: Path) -> None:
    (ep / "words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    lines = [f"[{mmss(s[0]['s'])}] {' '.join(w['w'] for w in s)}" for s in sentences(words)]
    (ep / "transcript.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load(ep: Path) -> list[dict]:
    return json.loads((ep / "words.json").read_text(encoding="utf-8"))
