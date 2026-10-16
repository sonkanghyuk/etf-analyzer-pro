"""SRT/VTT 불러오기·검사·내보내기. 내부 시간 단위는 정수 밀리초(ms)."""
from __future__ import annotations

import re
import uuid
from typing import Any

from .errors import StudioError

_TC = re.compile(
    r"(?P<a>\d{1,2}:)?(?P<b>\d{1,2}):(?P<c>\d{1,2})[,.](?P<ms>\d{1,3})\s*-->\s*"
    r"(?P<d>\d{1,2}:)?(?P<e>\d{1,2}):(?P<f>\d{1,2})[,.](?P<ms2>\d{1,3})"
)
_TAG = re.compile(r"</?[^>]{1,40}>")


def new_cue_id() -> str:
    return "c_" + uuid.uuid4().hex[:10]


def decode_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(손상 문자 대체)"


def _ms(h: str | None, m: str, s: str, ms: str) -> int:
    hours = int(h[:-1]) if h else 0
    return ((hours * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0")[:3])


def parse_subtitles(raw: bytes) -> dict[str, Any]:
    text, encoding = decode_bytes(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for bi, block in enumerate(blocks):
        lines = [ln for ln in block.split("\n")]
        tc_line = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if tc_line is None:
            if bi == 0 and lines and lines[0].strip().upper().startswith("WEBVTT"):
                continue
            if block.strip().upper().startswith(("NOTE", "STYLE", "REGION")):
                continue
            issues.append({"type": "no_timecode", "block": bi + 1, "message": f"{bi + 1}번째 블록에 타임코드가 없습니다."})
            continue
        m = _TC.search(lines[tc_line])
        if not m:
            issues.append({"type": "bad_timecode", "block": bi + 1, "message": f"{bi + 1}번째 블록 타임코드 형식 오류: {lines[tc_line][:60]}"})
            continue
        start = _ms(m.group("a"), m.group("b"), m.group("c"), m.group("ms"))
        end = _ms(m.group("d"), m.group("e"), m.group("f"), m.group("ms2"))
        body = "\n".join(ln.strip() for ln in lines[tc_line + 1:]).strip()
        body = _TAG.sub("", body)
        cue = {"id": new_cue_id(), "start_ms": start, "end_ms": end, "text": body, "flags": []}
        if end <= start:
            cue["flags"].append("reversed")
            issues.append({"type": "reversed", "cue_id": cue["id"], "message": f"{len(cues) + 1}번 자막: 끝 시각이 시작 시각보다 빠르거나 같습니다."})
        if not body:
            cue["flags"].append("empty")
            issues.append({"type": "empty", "cue_id": cue["id"], "message": f"{len(cues) + 1}번 자막이 비어 있습니다."})
        cues.append(cue)
    if not cues:
        raise StudioError("SUBTITLE_PARSE", "인식된 자막이 없습니다")
    cues.sort(key=lambda c: c["start_ms"])
    for prev, cur in zip(cues, cues[1:]):
        if cur["start_ms"] < prev["end_ms"]:
            cur["flags"].append("overlap")
            issues.append({"type": "overlap", "cue_id": cur["id"], "message": f"자막이 이전 자막과 겹칩니다 ({fmt_tc(cur['start_ms'])})."})
    if "손상" in encoding:
        issues.append({"type": "encoding", "message": "문자 인코딩을 확실히 알 수 없어 일부 글자가 깨졌을 수 있습니다."})
    return {"cues": cues, "issues": issues, "encoding": encoding}


def fmt_tc(ms: int, sep: str = ",") -> str:
    ms = max(0, int(round(ms)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{milli:03d}"


def to_srt(cues: list[dict[str, Any]]) -> str:
    out = []
    n = 0
    for cue in cues:
        if cue["end_ms"] <= cue["start_ms"]:
            continue
        n += 1
        out.append(f"{n}\n{fmt_tc(cue['start_ms'])} --> {fmt_tc(cue['end_ms'])}\n{cue['text']}\n")
    return "\n".join(out)


def parse_manual(text: str, duration_ms: int | None) -> list[dict[str, Any]]:
    """수동 자막 입력: 각 줄이 '00:01:02.5 - 00:01:05 문장' 또는 '62.5-65 문장' 형식.
    시각 없이 문장만 있는 줄은 받지 않는다(타이밍이 없으면 동기화가 불가능)."""
    cues = []
    pat = re.compile(r"^\s*([0-9:.,]+)\s*(?:-->|-|~)\s*([0-9:.,]+)\s+(.+)$")
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        m = pat.match(line)
        if not m:
            raise StudioError("SUBTITLE_PARSE", f"{i + 1}번째 줄: '시작 - 끝 문장' 형식이 아닙니다")
        a, b = parse_time(m.group(1)), parse_time(m.group(2))
        if b <= a:
            raise StudioError("SUBTITLE_PARSE", f"{i + 1}번째 줄: 끝 시각이 시작보다 빠릅니다")
        if duration_ms and a >= duration_ms:
            raise StudioError("SUBTITLE_PARSE", f"{i + 1}번째 줄: 영상 길이를 넘습니다")
        cues.append({"id": new_cue_id(), "start_ms": a, "end_ms": min(b, duration_ms or b), "text": m.group(3).replace("\\n", "\n"), "flags": []})
    if not cues:
        raise StudioError("SUBTITLE_PARSE", "입력된 자막이 없습니다")
    cues.sort(key=lambda c: c["start_ms"])
    return cues


def parse_time(value: str) -> int:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 1:
            return int(round(float(parts[0]) * 1000))
        if len(parts) == 2:
            return int(round((int(parts[0]) * 60 + float(parts[1])) * 1000))
        if len(parts) == 3:
            return int(round((int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])) * 1000))
    except ValueError:
        pass
    raise StudioError("SUBTITLE_PARSE", f"시각 형식 오류: {value}")
