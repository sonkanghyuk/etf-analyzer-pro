"""글꼴 목록과 글리프 확인.

동봉 글꼴은 SIL OFL 1.1인 나눔 글꼴만 사용한다(fonts/OFL-NANUM.txt).
Windows 시스템 글꼴(맑은 고딕)은 동봉하지 않고, 설치되어 있을 때만 '시스템 글꼴'로 쓴다.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

from PIL import ImageFont

from . import config

FALLBACK_FONT_ID = "nanum-gothic"

_BUNDLED = [
    ("nanum-gothic", "나눔고딕", "NanumGothic.ttf", "NanumGothicBold.ttf"),
    ("nanum-square", "나눔스퀘어", "NanumSquareR.ttf", "NanumSquareB.ttf"),
    ("nanum-square-round", "나눔스퀘어라운드", "NanumSquareRoundR.ttf", "NanumSquareRoundB.ttf"),
]

_WINDOWS_SYSTEM = [
    ("malgun", "맑은 고딕(시스템)", "malgun.ttf", "malgunbd.ttf"),
]


@functools.lru_cache(maxsize=1)
def _scan() -> dict[str, dict]:
    fonts: dict[str, dict] = {}
    for fid, name, reg, bold in _BUNDLED:
        rp, bp = config.BUNDLED_FONTS_DIR / reg, config.BUNDLED_FONTS_DIR / bold
        if rp.exists():
            fonts[fid] = {"id": fid, "name": name, "regular": str(rp), "bold": str(bp if bp.exists() else rp),
                          "license": "SIL OFL 1.1 (동봉)", "source": "bundled"}
    windir = os.environ.get("WINDIR")
    if windir:
        fdir = Path(windir) / "Fonts"
        for fid, name, reg, bold in _WINDOWS_SYSTEM:
            rp, bp = fdir / reg, fdir / bold
            if rp.exists():
                fonts[fid] = {"id": fid, "name": name, "regular": str(rp), "bold": str(bp if bp.exists() else rp),
                              "license": "Windows 시스템 글꼴(동봉하지 않음)", "source": "system"}
    if config.FONTS_USER_DIR.exists():
        for p in sorted(config.FONTS_USER_DIR.iterdir()):
            if p.suffix.lower() in (".ttf", ".otf"):
                fid = "user-" + p.stem.lower().replace(" ", "-")
                fonts[fid] = {"id": fid, "name": p.stem + " (사용자)", "regular": str(p), "bold": str(p),
                              "license": "사용자 제공 — 이용 조건 확인 필요", "source": "user"}
    return fonts


def refresh() -> None:
    _scan.cache_clear()
    load_font.cache_clear()
    _cmap.cache_clear()


def list_fonts() -> list[dict]:
    return list(_scan().values())


def resolve(font_id: str | None) -> tuple[dict, bool]:
    """(글꼴 정보, 대체 여부)"""
    fonts = _scan()
    if font_id and font_id in fonts:
        return fonts[font_id], False
    return fonts[FALLBACK_FONT_ID], True


@functools.lru_cache(maxsize=256)
def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size, layout_engine=ImageFont.Layout.BASIC)


@functools.lru_cache(maxsize=16)
def _cmap(path: str) -> frozenset[int]:
    from fontTools.ttLib import TTFont

    tt = TTFont(path, lazy=True, fontNumber=0)
    codes: set[int] = set()
    for table in tt["cmap"].tables:
        codes.update(table.cmap.keys())
    return frozenset(codes)


def missing_glyphs(path: str, text: str) -> list[str]:
    cmap = _cmap(path)
    seen: list[str] = []
    for ch in text:
        if ch.isspace() or ch in seen:
            continue
        if ord(ch) not in cmap:
            seen.append(ch)
    return seen


def file_signature() -> str:
    parts = []
    for f in _scan().values():
        for key in ("regular", "bold"):
            try:
                st = os.stat(f[key])
                parts.append(f"{f['id']}:{key}:{st.st_size}")
            except OSError:
                pass
    return "|".join(parts)
