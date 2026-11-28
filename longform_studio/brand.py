"""brand.yaml 로드, 폰트 찾기, 색 변환."""
from __future__ import annotations

import functools
import os
from pathlib import Path

import yaml
from PIL import ImageFont

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
FONT_DIRS = [PKG / "fonts", ROOT / "johnber_shorts_studio" / "fonts",
             Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
             Path("/usr/share/fonts"), Path.home() / "Library/Fonts", Path("/Library/Fonts")]


@functools.lru_cache(maxsize=1)
def brand() -> dict:
    b = yaml.safe_load((PKG / "brand.yaml").read_text(encoding="utf-8"))
    if b.get("color_convention") == "kr":
        b["colors"]["up"], b["colors"]["down"] = b["colors"]["up_kr"], b["colors"]["down_kr"]
    return b


def set_convention(conv: str | None) -> None:
    if conv and conv != brand().get("color_convention"):
        b = brand()
        c = b["colors"]
        if conv == "kr":
            c["up"], c["down"] = c["up_kr"], c["down_kr"]
        b["color_convention"] = conv


def color(name: str) -> tuple[int, int, int]:
    h = brand()["colors"].get(name, name).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@functools.lru_cache(maxsize=None)
def font_path(role: str) -> Path:
    for name in brand()["fonts"][role]["files"]:
        for d in FONT_DIRS:
            if d.is_dir():
                hits = list(d.rglob(name)) if d.name in ("fonts", "Fonts") and len(str(d)) < 40 else [d / name]
                for p in hits:
                    if p.is_file():
                        return p
    raise FileNotFoundError(f"{role} 폰트를 찾지 못했습니다: {brand()['fonts'][role]['files']}")


@functools.lru_cache(maxsize=None)
def font(role: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path(role)), px)
