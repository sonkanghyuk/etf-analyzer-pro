"""자막 청크 나누기(바이블 §6) + ASS(고정 폭 라운드 바)·SRT 쓰기.

단어 = {"s": 시작초, "e": 끝초, "w": "어절"}; 문장 = 단어 리스트.
"""
from __future__ import annotations

import math
import re

from .brand import brand

UNIT = re.compile(r"^(%|%p|퍼센트|포인트|달러|원|원대|억|조|만|천|배|주|bp|개|위|년|월|일|분기|선|대)")
NUM_END = re.compile(r"[\d.,]$")
JOINED = [("S&P", r"^500"), ("나스닥", r"^100"), ("다우", r"^존스"), ("러셀", r"^2000")]
PREFER_END = re.compile(r"(,|는데|은데|인데|하고|하며|면서|지만|니까|으면|라면|다면|고|며|서|면)$")
NO_END = re.compile(r"(의|및|각|약|총|더|또|그|저|그런|어떤|모든|하는|되는|있는|없는|하던|이런|저런|"
                    r"잘못|다시|바로|직접|크게|가장|더욱|아주|매우|너무|꽤|잘|못|안|계속|함께|이미|아직|곧|먼저|무려|약간|조금)$")
OK_RIEUL = re.compile(r"(을|를|월|일|들|말|글|물|발|달|할)$")


def _rieul_modifier(word: str) -> bool:
    """마지막 글자 받침이 ㄹ인 관형형(만들어드릴, 오를, 갈) — 뒤 명사와 떼지 않는다."""
    ch = word.rstrip(",.?!")[-1:] if word else ""
    return bool(ch) and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 8 and not OK_RIEUL.search(word)
FILLERS = {"어", "음", "아", "그", "어어", "음음", "에", "뭐"}


def _len(tokens: list[str]) -> int:
    return len(" ".join(tokens))


AUX_AFTER_GO = re.compile(r"^(있|없|싶|계시|계신|계셨)")
AUX_AFTER_EO = re.compile(r"^(보|봐|봤|볼|주|줘|준|줄|드리|드릴|드립|두|둔|둘|놓|버리|버린|있|오|와|온|가|간|갈)")


def can_break(prev: str, nxt: str) -> bool:
    if NUM_END.search(prev) and UNIT.match(nxt):
        return False
    p = prev.rstrip(",")
    if p == prev and p.endswith("고") and AUX_AFTER_GO.match(nxt):      # 보유하고 있는
        return False
    if p == prev and re.search(r"(어|아|여|해|워|와|봐|겨|져|쳐|켜|려)$", p) and AUX_AFTER_EO.match(nxt):  # 눈여겨 볼
        return False
    for a, b in JOINED:
        if prev.endswith(a) and re.match(b, nxt):
            return False
    return True


def split_sentence(tokens: list[str], max_chars: int | None = None) -> list[tuple[int, int]]:
    """토큰 인덱스 구간 [(i, j), ...] — DP로 청크 수 최소 + 끊는 자리 품질 + 균등 길이."""
    mx = max_chars or brand()["subtitle_rules"]["max_chars"]
    n = len(tokens)
    if n == 0:
        return []
    total = _len(tokens)
    target = total / max(1, math.ceil(total / mx))
    INF = float("inf")
    dp = [INF] * (n + 1)
    back = [0] * (n + 1)
    dp[0] = 0.0
    for j in range(1, n + 1):
        if j < n and not can_break(tokens[j - 1], tokens[j]):
            continue
        for i in range(j - 1, -1, -1):
            ln = _len(tokens[i:j])
            if ln > mx and j - i > 1:
                break
            if dp[i] == INF:
                continue
            cost = 100.0 + 0.5 * abs(ln - target)
            if j < n:
                last = tokens[j - 1]
                if PREFER_END.search(last):
                    cost -= 8
                if NO_END.search(last) or _rieul_modifier(last):
                    cost += 25
            if dp[i] + cost < dp[j]:
                dp[j], back[j] = dp[i] + cost, i
    if dp[n] == INF:  # 끊을 수 없는 긴 묶음 — 글자 수 기준으로 강제
        out, i = [], 0
        while i < n:
            j = i + 1
            while j < n and _len(tokens[i:j + 1]) <= mx:
                j += 1
            out.append((i, j))
            i = j
        return out
    out, j = [], n
    while j > 0:
        out.append((back[j], j))
        j = back[j]
    return out[::-1]


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[.。]+$", "", text)          # 마침표 제거, ?!, 는 유지
    return text.replace("{", "(").replace("}", ")")


def make_cues(sentences: list[list[dict]], drop_fillers: bool = True) -> list[dict]:
    r = brand()["subtitle_rules"]
    cues = []
    for sent in sentences:
        words = [w for w in sent if not (drop_fillers and w["w"].strip(",. ") in FILLERS)]
        if not words:
            continue
        toks = [w["w"].strip() for w in words]
        for i, j in split_sentence(toks):
            cues.append({"s": words[i]["s"], "e": words[j - 1]["e"], "text": clean_text(" ".join(toks[i:j]))})
    # 말이 짧아 0.8초도 안 되는 청크는 앞 청크와 합친다(합쳐도 max_chars 이하일 때)
    merged = []
    for c in cues:
        if merged and c["e"] - c["s"] < r["min_duration"] and \
                len(merged[-1]["text"]) + 1 + len(c["text"]) <= r["max_chars"] and c["s"] - merged[-1]["e"] < 0.3:
            merged[-1] = {"s": merged[-1]["s"], "e": c["e"], "text": f"{merged[-1]['text']} {c['text']}"}
        else:
            merged.append(c)
    cues = merged
    # 표시 시간: 다음 자막 시작까지 이어 붙이되, 쉼이 길면 끝 + tail 에서 끔
    for k, c in enumerate(cues):
        nxt = cues[k + 1]["s"] if k + 1 < len(cues) else None
        end = c["e"] + r["tail_after_gap"]
        if nxt is not None:
            end = nxt if nxt - c["e"] <= r["hold_gap_max"] else min(end, nxt)
        if end - c["s"] < r["min_duration"]:
            end = c["s"] + r["min_duration"] if nxt is None else min(nxt, c["s"] + r["min_duration"])
        c["e"] = max(end, c["s"] + 0.1)
    return cues


def _ts(t: float, sep: str = ",", cs: bool = False) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    if cs:
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int(round((s % 1) * 1000)) % 1000:03d}"


def write_srt(cues: list[dict], path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{_ts(c['s'])} --> {_ts(c['e'])}\n{c['text']}\n\n")


def bar_path(w: int, h: int, r: int) -> str:
    k = 0.5523 * r
    return (f"m {r} 0 l {w - r} 0 b {w - r + k:.1f} 0 {w} {r - k:.1f} {w} {r} l {w} {h - r} "
            f"b {w} {h - r + k:.1f} {w - r + k:.1f} {h} {w - r} {h} l {r} {h} b {r - k:.1f} {h} 0 {h - r + k:.1f} 0 {h - r} "
            f"l 0 {r} b 0 {r - k:.1f} {r - k:.1f} 0 {r} 0")


def write_ass(cues: list[dict], path) -> None:
    b = brand()
    L, F = b["layout"]["subtitle_bar"], b["fonts"]["subtitle"]
    w, h = L["x1"] - L["x0"], L["y1"] - L["y0"]
    alpha = f"{round(255 * (1 - L['opacity'])):02X}"
    cx, cy = (L["x0"] + L["x1"]) / 2 - 1, (L["y0"] + L["y1"]) / 2
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {b['canvas']['width']}
PlayResY: {b['canvas']['height']}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bar,{F['ass_name']},20,&H{alpha}000000,&H{alpha}000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Sub,{F['ass_name']},{F['ass_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path_cmd = bar_path(w, h, L["radius"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(head)
        for c in cues:
            s, e = _ts(c["s"], cs=True), _ts(c["e"], cs=True)
            f.write(f"Dialogue: 0,{s},{e},Bar,,0,0,0,,{{\\pos({L['x0']},{L['y0']})\\p1}}{path_cmd}{{\\p0}}\n")
            f.write(f"Dialogue: 1,{s},{e},Sub,,0,0,0,,{{\\pos({cx:.0f},{cy:.0f})}}{c['text']}\n")
