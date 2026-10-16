"""음성인식 (faster-whisper). 결과는 transcript.json으로 저장해 다시 쓸 수 있습니다.

transcript 형식:
{"language": "ko", "duration": 3600.0, "segments": [
  {"id": 0, "start": 1.2, "end": 4.8, "text": "...", "words": [{"start": 1.2, "end": 1.6, "word": "안녕하세요"}, ...]}
]}
"""

import json
from pathlib import Path
from typing import Callable


def transcribe(
    audio: Path,
    offset: float = 0.0,
    model_size: str = "small",
    language: str = "ko",
    device: str = "auto",
    on_progress: Callable[[float], None] | None = None,
) -> dict:
    from faster_whisper import WhisperModel

    # CPU에서는 int8이 빠르고 품질 차이가 거의 없습니다.
    compute_type = "int8" if device in ("auto", "cpu") else "default"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(audio),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    out = []
    for seg in segments:
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
