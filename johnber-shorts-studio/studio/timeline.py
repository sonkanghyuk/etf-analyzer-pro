"""Non-destructive EDL math. All source and output times are float seconds.

Only the encoder rounds to its 1/30 s frame grid; no cumulative per-edit rounding
is applied. Cuts are absolute source times, merged before mapping any stream.
"""
from __future__ import annotations

import math
from copy import deepcopy


def _number(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: 유효한 숫자를 입력하세요.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name}: 유한한 숫자를 입력하세요.")
    return result


def _bounds(clip):
    start = _number(clip.get("start", 0), "시작 시각")
    end = _number(clip.get("end", 0), "끝 시각")
    speed = _number(clip.get("speed", 1), "배속")
    if start < 0 or end <= start:
        raise ValueError("클립 시작은 0 이상이며 끝 시각보다 작아야 합니다.")
    if not 0.25 <= speed <= 4:
        raise ValueError("배속은 0.25~4.0 범위에서 설정하세요.")
    return start, end, speed


def segments(clip: dict) -> list[dict]:
    """Return chronological, nonempty kept spans in absolute source seconds."""
    start, end, _ = _bounds(clip)
    cuts = []
    for cut in clip.get("cuts", []):
        a = _number(cut.get("start"), "삭제 시작")
        b = _number(cut.get("end"), "삭제 끝")
        if b <= a:
            raise ValueError("삭제 구간의 끝 시각은 시작보다 커야 합니다.")
        a, b = max(start, a), min(end, b)
        if b > a:
            cuts.append((a, b))
    merged = []
    for a, b in sorted(cuts):
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    kept, cursor = [], start
    for a, b in merged:
        if a > cursor + 1e-9:
            kept.append({"start": cursor, "end": a})
        cursor = max(cursor, b)
    if end > cursor + 1e-9:
        kept.append({"start": cursor, "end": end})
    return kept


def duration(clip: dict) -> float:
    _, _, speed = _bounds(clip)
    return sum(s["end"] - s["start"] for s in segments(clip)) / speed


def source_time(clip: dict, output_time: float) -> float:
    """Map output seconds through cuts and speed. Endpoint maps to source end."""
    spans = segments(clip)
    if not spans:
        raise ValueError("모든 영상 구간이 삭제되어 출력할 내용이 없습니다.")
    _, _, speed = _bounds(clip)
    elapsed = max(0.0, _number(output_time, "미리보기 시각")) * speed
    for span in spans:
        span_duration = span["end"] - span["start"]
        if elapsed < span_duration - 1e-9:
            return span["start"] + elapsed
        elapsed -= span_duration
    return spans[-1]["end"]


def mapped_cues(clip: dict, cues: list[dict]) -> list[dict]:
    """Split captions at EDL cuts; remap all timing from the same kept spans."""
    _, _, speed = _bounds(clip)
    result, offset = [], 0.0
    for span in segments(clip):
        for cue in cues:
            a = _number(cue.get("start"), "자막 시작")
            b = _number(cue.get("end"), "자막 끝")
            if b <= a:
                raise ValueError("자막 끝 시각은 시작보다 커야 합니다.")
            begin, finish = max(a, span["start"]), min(b, span["end"])
            if finish <= begin:
                continue
            item = deepcopy(cue)
            item.update(start=offset + (begin - span["start"]) / speed,
                        end=offset + (finish - span["start"]) / speed,
                        source_start=begin, source_end=finish,
                        source_id=cue.get("id"))
            result.append(item)
        offset += (span["end"] - span["start"]) / speed
    return sorted(result, key=lambda c: (c["start"], c["end"]))
