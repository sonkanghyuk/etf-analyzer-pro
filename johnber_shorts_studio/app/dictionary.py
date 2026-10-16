"""사용자 사전: 인식 보조(전사 힌트)와 교정 제안. 자동 치환은 하지 않는다."""
from __future__ import annotations

import re

from . import db

DEFAULT_WORDS = ["SOXL", "TQQQ", "SCHD", "SOXX", "SMH", "엔비디아", "커버드콜", "분배금", "삼성전자", "SK하이닉스", "CXMT"]

_TOKEN = re.compile(r"[A-Za-z]+|[가-힣A-Za-z0-9]+")
_NUM = re.compile(r"\d")
_TICKER = re.compile(r"\b[A-Z]{2,6}\b")


def words() -> list[str]:
    return db.get_setting("dictionary", DEFAULT_WORDS)


def set_words(items: list[str]) -> list[str]:
    clean = []
    for w in items:
        w = w.strip()
        if w and w not in clean:
            clean.append(w[:40])
    db.set_setting("dictionary", clean)
    return clean


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def suggestions(cues: list[dict], vocab: list[str] | None = None) -> list[dict]:
    vocab = vocab or words()
    out = []
    for cue in cues:
        for m in _TOKEN.finditer(cue.get("text", "")):
            tok = m.group(0)
            for w in vocab:
                if tok == w or tok.startswith(w):
                    continue
                cand = None
                if w.isascii() and tok.isascii():
                    if tok.lower() == w.lower():
                        cand = "대소문자"
                    elif len(w) >= 4 and abs(len(tok) - len(w)) <= 1 and _lev(tok.upper(), w.upper()) == 1:
                        cand = "철자 1자 차이"
                elif not w.isascii() and len(w) >= 3 and len(tok) >= len(w):
                    if _lev(tok[: len(w)], w) == 1:
                        cand = "음절 1자 차이"
                if cand:
                    out.append({"cue_id": cue["id"], "found": tok, "suggestion": w, "reason": cand,
                                "start": m.start(), "end": m.end()})
    return out


def check_flags(text: str) -> list[str]:
    flags = []
    if _NUM.search(text):
        flags.append("number")
    if _TICKER.search(text):
        flags.append("ticker")
    return flags
