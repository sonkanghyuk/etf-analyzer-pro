"""클립 구간의 자막을 화면용으로 나누고 ASS(영상에 입힘) / SRT(업로드용)로 씁니다."""

import re

from .templates import Template

PLAY_W, PLAY_H = 1080, 1920
PUNCT_END = re.compile(r"[.?!,…]$")


def caption_chunks(segments: list[dict], start: float, end: float, max_chars: int = 16) -> list[dict]:
    """[{start, end, text}] — 클립 시작 기준 초. 단어 타임스탬프가 있으면 그걸로 나눕니다."""
    words = []
    for s in segments:
        if s["end"] <= start or s["start"] >= end:
            continue
        if s.get("words"):
            words += [w for w in s["words"] if w["end"] > start and w["start"] < end]
        else:
            words += _spread_words(s)
    chunks: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            chunks.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(w["word"] for w in cur)})
            cur.clear()

    for w in words:
        if cur:
            text_len = len(" ".join(x["word"] for x in cur + [w]))
            gap = w["start"] - cur[-1]["end"]
            if text_len > max_chars or gap > 0.5 or w["end"] - cur[0]["start"] > 3.0:
                flush()
        cur.append(w)
        if PUNCT_END.search(w["word"]):
            flush()
    flush()

    out = []
    for c in chunks:
        a, b = max(c["start"], start) - start, min(c["end"], end) - start
        if b - a < 0.05:
            continue
        out.append({"start": round(a, 3), "end": round(b, 3), "text": c["text"]})
    # 자막 사이 짧은 공백은 앞 자막을 늘려 깜빡임을 없앱니다.
    for x, y in zip(out, out[1:]):
        if 0 < y["start"] - x["end"] < 0.3:
            x["end"] = y["start"]
    return out


def _spread_words(seg: dict) -> list[dict]:
    """단어 타임스탬프가 없는 세그먼트: 글자 수 비율로 시간 배분."""
    words = seg["text"].split()
    total = sum(len(w) for w in words) or 1
    t, out = seg["start"], []
    for w in words:
        d = (seg["end"] - seg["start"]) * len(w) / total
        out.append({"start": t, "end": t + d, "word": w})
        t += d
    return out


# ---------- SRT ----------

def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(chunks: list[dict]) -> str:
    return "\n".join(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n" for i, c in enumerate(chunks, 1))


# ---------- ASS ----------

def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", " ")


def _style(name: str, font: str, st: dict, alignment: int) -> str:
    box = st.get("box")
    # BorderStyle 3 = 글자 뒤 불투명 박스(BackColour 대신 OutlineColour가 박스 색)
    border_style, outline_colour, outline = (3, box, 14) if box else (1, "&H00000000", st.get("outline", 0))
    return (
        f"Style: {name},{font},{st['size']},{st['color']},&H000000FF,{outline_colour},&H80000000,"
        f"-1,0,0,0,100,100,0,0,{border_style},{outline},{st.get('shadow', 0)},{alignment},70,70,{st['margin_v']},1"
    )


def to_ass(chunks: list[dict], title: str, duration: float, tpl: Template, font: str) -> str:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {PLAY_W}",
        f"PlayResY: {PLAY_H}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding",
        _style("Caption", font, tpl.caption, 2),
    ]
    if tpl.title:
        lines.append(_style("Title", font, tpl.title, 8))
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    if tpl.title and title:
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(duration)},Title,,0,0,0,,{ass_escape(title)}")
    hl = tpl.caption.get("highlight")
    for c in chunks:
        text = ass_escape(c["text"])
        if hl:
            # 가장 긴 단어(대개 핵심어)를 강조색으로
            key = max(text.split(), key=len, default="")
            if len(key) >= 2:
                text = text.replace(key, f"{{\\c{hl}}}{key}{{\\c{tpl.caption['color']}}}", 1)
        lines.append(f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Caption,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"
