"""편집 결정 목록(EDL)과 시간 매핑.

시간 축은 세 가지다.
  - 원본 시간(source): 원본 파일 기준 ms
  - 편집 시간(edited): 삭제 구간을 뺀 뒤의 시간
  - 출력 시간(output): 편집 시간 / 배속

규칙(문서화된 반올림):
  1. 내부 단위는 정수 ms. 계산 중에는 float를 쓰고 외부로 낼 때 반올림한다.
  2. 남길 구간(kept segment)의 길이는 출력 프레임 격자(1000/fps ms)에 맞춰 반올림한다.
     렌더러는 같은 길이로 영상 프레임 수와 오디오 샘플 수를 맞추므로 구간이 많아져도
     영상·음성 사이 누적 오차가 생기지 않는다.
  3. 한 프레임보다 짧은 남는 조각은 버린다.
  4. 자막·강조·영상·오디오 모두 이 모듈의 매핑 하나만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_FPS = 30
SPEED_MIN, SPEED_MAX = 0.5, 2.5


@dataclass(frozen=True)
class Segment:
    src_start: int      # 원본 시작 ms
    src_end: int        # 원본 끝 ms (정렬 기준, 실제 재생 끝은 src_start + dur)
    dur: float          # 프레임 격자에 맞춘 편집 길이(ms)
    edit_start: float   # 편집 시간에서의 시작 ms


def merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted((int(a), int(b)) for a, b in ranges if b > a):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def active_cuts(clip: dict[str, Any]) -> list[tuple[int, int]]:
    return merge_ranges((c["start_ms"], c["end_ms"]) for c in clip.get("cuts", []) if c.get("enabled", True))


def kept_segments(clip: dict[str, Any], fps: int = DEFAULT_FPS) -> list[Segment]:
    start, end = int(clip["range"]["start_ms"]), int(clip["range"]["end_ms"])
    frame = 1000.0 / fps
    pieces: list[tuple[int, int]] = []
    cursor = start
    for a, b in active_cuts(clip):
        if b <= start or a >= end:
            continue
        a, b = max(a, start), min(b, end)
        if a > cursor:
            pieces.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < end:
        pieces.append((cursor, end))
    segs: list[Segment] = []
    edit = 0.0
    for a, b in pieces:
        frames = round((b - a) / frame)
        if frames < 1:
            continue
        dur = frames * frame
        segs.append(Segment(a, b, dur, edit))
        edit += dur
    return segs


def speed_of(clip: dict[str, Any]) -> float:
    s = float(clip.get("speed") or 1.0)
    return min(SPEED_MAX, max(SPEED_MIN, s))


def edited_duration(segs: list[Segment]) -> float:
    return sum(s.dur for s in segs)


def output_duration_ms(clip: dict[str, Any], fps: int = DEFAULT_FPS) -> float:
    return edited_duration(kept_segments(clip, fps)) / speed_of(clip)


def source_to_edited(t: float, segs: list[Segment]) -> float | None:
    for s in segs:
        if s.src_start <= t <= s.src_start + s.dur:
            return s.edit_start + (t - s.src_start)
    return None


def source_to_output(t: float, segs: list[Segment], speed: float) -> float | None:
    e = source_to_edited(t, segs)
    return None if e is None else e / speed


def output_to_source(t_out: float, segs: list[Segment], speed: float) -> float | None:
    e = t_out * speed
    for s in segs:
        if s.edit_start <= e <= s.edit_start + s.dur:
            return s.src_start + (e - s.edit_start)
    return None


def _map_interval(a: float, b: float, segs: list[Segment]) -> tuple[float, float] | None:
    """원본 구간 [a,b]를 편집 시간 구간으로. 중간 삭제는 이어 붙인다."""
    first = last = None
    for s in segs:
        s_end = s.src_start + s.dur
        lo, hi = max(a, s.src_start), min(b, s_end)
        if hi <= lo:
            continue
        e_lo = s.edit_start + (lo - s.src_start)
        e_hi = s.edit_start + (hi - s.src_start)
        if first is None:
            first = e_lo
        last = e_hi
    if first is None or last is None or last - first < 1:
        return None
    return first, last


def map_cues(clip: dict[str, Any], fps: int = DEFAULT_FPS) -> list[dict[str, Any]]:
    """클립 자막을 출력 시간으로 변환한다. 발화가 삭제된 자막은 제외."""
    segs = kept_segments(clip, fps)
    speed = speed_of(clip)
    out = []
    for cue in clip.get("cues", []):
        if cue.get("deleted_speech") or not cue.get("text", "").strip():
            continue
        iv = _map_interval(cue["start_ms"], cue["end_ms"], segs)
        if iv is None:
            continue
        out.append({**cue, "out_start_ms": iv[0] / speed, "out_end_ms": iv[1] / speed})
    # 겹침 방지: 다음 자막이 시작되면 이전 자막을 끝낸다(동시에 두 줄이 겹쳐 보이지 않게)
    out.sort(key=lambda c: c["out_start_ms"])
    for prev, cur in zip(out, out[1:]):
        if prev["out_end_ms"] > cur["out_start_ms"]:
            prev["out_end_ms"] = cur["out_start_ms"]
    return [c for c in out if c["out_end_ms"] - c["out_start_ms"] >= 1]


def summarize(clip: dict[str, Any], fps: int = DEFAULT_FPS) -> dict[str, Any]:
    segs = kept_segments(clip, fps)
    speed = speed_of(clip)
    src_len = clip["range"]["end_ms"] - clip["range"]["start_ms"]
    edited = edited_duration(segs)
    return {
        "source_ms": src_len,
        "removed_ms": src_len - edited,
        "edited_ms": edited,
        "output_ms": edited / speed,
        "speed": speed,
        "segments": [{"src_start": s.src_start, "dur": s.dur, "edit_start": s.edit_start} for s in segs],
    }
