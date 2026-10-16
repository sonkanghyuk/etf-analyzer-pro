"""장면 레이아웃과 텍스트 렌더러.

미리보기와 최종 MP4는 이 모듈이 만든 같은 PNG(배경·전경·자막)를 사용한다.
브라우저는 그 PNG를 축소해서 겹쳐 보여주고, FFmpeg는 같은 PNG를 원본 크기로 합성한다.
따라서 글꼴·줄바꿈·위치가 엔진마다 달라지지 않는다.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from . import config, fonts

RENDERER_VERSION = "layout-v1"
CANVAS_W, CANVAS_H = 1080, 1920

OVERLAY_DIR = config.CACHE_DIR / "overlays"


# ---------------------------------------------------------------- 기본 스타일

def _text_style(**kw: Any) -> dict[str, Any]:
    base = {
        "enabled": True,
        "font": "nanum-square",
        "size": 64,
        "bold": True,
        "color": "#FFFFFF",
        "letter_spacing": 0,
        "line_height": 1.25,
        "align": "center",
        "stroke_width": 0,
        "stroke_color": "#000000",
        "shadow": {"enabled": False, "dx": 4, "dy": 4, "color": "#000000", "opacity": 0.6, "blur": 2},
        "bg": {"enabled": False, "color": "#000000", "opacity": 0.6, "pad_x": 28, "pad_y": 14, "radius": 18, "mode": "block"},
        "box": {"x": 60, "y": 200, "w": 960},
        "anchor_y": "top",
        "max_lines": 2,
        "auto_shrink": True,
        "min_size": 36,
    }
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def default_style(variant: str = "dark") -> dict[str, Any]:
    if variant == "light":
        return {
            "schema": 1,
            "canvas": {"bg_color": "#F4F1EA", "bg_asset_id": None},
            "video": {"box": {"x": 0, "y": 600, "w": 1080, "h": 640}, "fit": "contain",
                      "crop": {"enabled": False, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "masks": []},
            "title": _text_style(font="nanum-square", size=76, color="#14213D", box={"x": 60, "y": 230, "w": 960},
                                 anchor_y="top", max_lines=3, line_height=1.22),
            "subtitle": _text_style(font="nanum-gothic", size=54, color="#111111", box={"x": 70, "y": 1330, "w": 940},
                                    bg={"enabled": True, "color": "#FFFFFF", "opacity": 0.95, "pad_x": 26, "pad_y": 14, "radius": 16, "mode": "line"},
                                    max_lines=2),
            "emphasis": {"color": "#D7263D", "bold": True, "scale": 1.0, "bg_enabled": False, "bg_color": "#FFE066"},
            "fixed_text": _text_style(enabled=False, text="", font="nanum-gothic", size=34, bold=False, color="#555555",
                                      box={"x": 60, "y": 1740, "w": 960}, max_lines=1),
            "logo": {"enabled": False, "asset_id": None, "x": 860, "y": 90, "w": 160, "opacity": 1.0},
            "safe_area": {"top": 150, "bottom": 330, "right": 140, "show": True},
        }
    if variant == "minimal":
        return {
            "schema": 1,
            "canvas": {"bg_color": "#121212", "bg_asset_id": None},
            "video": {"box": {"x": 0, "y": 520, "w": 1080, "h": 720}, "fit": "contain",
                      "crop": {"enabled": False, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "masks": []},
            "title": _text_style(font="nanum-gothic", size=62, color="#FFFFFF", box={"x": 70, "y": 290, "w": 940},
                                 anchor_y="top", max_lines=2, align="left"),
            "subtitle": _text_style(font="nanum-gothic", size=50, color="#FFFFFF", box={"x": 80, "y": 1290, "w": 920},
                                    bg={"enabled": True, "color": "#000000", "opacity": 0.55, "pad_x": 22, "pad_y": 12, "radius": 12, "mode": "block"},
                                    max_lines=2),
            "emphasis": {"color": "#6EE7B7", "bold": True, "scale": 1.0, "bg_enabled": False, "bg_color": "#000000"},
            "fixed_text": _text_style(enabled=False, text="", font="nanum-gothic", size=32, bold=False, color="#9CA3AF",
                                      box={"x": 70, "y": 1760, "w": 940}, max_lines=1, align="left"),
            "logo": {"enabled": False, "asset_id": None, "x": 880, "y": 110, "w": 140, "opacity": 0.9},
            "safe_area": {"top": 150, "bottom": 330, "right": 140, "show": True},
        }
    return {
        "schema": 1,
        "canvas": {"bg_color": "#000000", "bg_asset_id": None},
        "video": {"box": {"x": 0, "y": 600, "w": 1080, "h": 640}, "fit": "contain",
                  "crop": {"enabled": False, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "masks": []},
        "title": _text_style(font="nanum-square", size=80, color="#FFFFFF", box={"x": 50, "y": 220, "w": 980},
                             anchor_y="top", max_lines=3, line_height=1.2),
        "subtitle": _text_style(font="nanum-square", size=58, color="#FFFFFF", box={"x": 60, "y": 1320, "w": 960},
                                stroke_width=5, stroke_color="#000000", max_lines=2),
        "emphasis": {"color": "#FFD400", "bold": True, "scale": 1.0, "bg_enabled": False, "bg_color": "#000000"},
        "fixed_text": _text_style(enabled=False, text="", font="nanum-gothic", size=34, bold=False, color="#BBBBBB",
                                  box={"x": 60, "y": 1740, "w": 960}, max_lines=1),
        "logo": {"enabled": False, "asset_id": None, "x": 860, "y": 90, "w": 160, "opacity": 1.0},
        "safe_area": {"top": 150, "bottom": 330, "right": 140, "show": True},
    }


BUILTIN_TEMPLATES = [
    ("tpl_builtin_dark", "① 강의 보존 · 검은 배경 큰 제목", "dark"),
    ("tpl_builtin_light", "② 자료 가독성 · 밝은 배경", "light"),
    ("tpl_builtin_minimal", "③ 미니멀 강의형", "minimal"),
]


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def normalize_style(style: dict[str, Any] | None) -> dict[str, Any]:
    """누락 필드를 기본값으로 채운다(오래된 템플릿과의 호환)."""
    return deep_merge(default_style("dark"), style or {})


# ---------------------------------------------------------------- 색상 도우미

def rgba(color: str | None, opacity: float = 1.0) -> tuple[int, int, int, int]:
    c = (color or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        a = int(c[6:8], 16) if len(c) >= 8 else 255
    except ValueError:
        r, g, b, a = 0, 0, 0, 255
    return r, g, b, int(round(a * max(0.0, min(1.0, float(opacity)))))


# ---------------------------------------------------------------- 줄바꿈

def _font_for(style: dict[str, Any], emphasized: bool, emph: dict[str, Any], size: int):
    info, substituted = fonts.resolve(style.get("font"))
    bold = bool(style.get("bold")) or (emphasized and bool(emph.get("bold")))
    path = info["bold"] if bold else info["regular"]
    s = int(round(size * (float(emph.get("scale", 1.0)) if emphasized else 1.0)))
    return fonts.load_font(path, max(8, s)), path, substituted


def _char_flags(text: str, spans: list[list[int]] | None) -> list[bool]:
    flags = [False] * len(text)
    for span in spans or []:
        try:
            a, b = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            continue
        for i in range(max(0, a), min(len(text), b)):
            flags[i] = True
    return flags


def _runs(chars: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    runs: list[tuple[str, bool]] = []
    for ch, f in chars:
        if runs and runs[-1][1] == f:
            runs[-1] = (runs[-1][0] + ch, f)
        else:
            runs.append((ch, f))
    return runs


def _measure(chars: list[tuple[str, bool]], style: dict, emph: dict, size: int) -> float:
    ls = float(style.get("letter_spacing", 0))
    total = 0.0
    for text, f in _runs(chars):
        font, _, _ = _font_for(style, f, emph, size)
        if ls:
            total += sum(font.getlength(ch) for ch in text) + ls * len(text)
        else:
            total += font.getlength(text)
    return total


def wrap(text: str, spans: list[list[int]] | None, style: dict, emph: dict, size: int, max_w: float) -> list[list[tuple[str, bool]]]:
    """실제 글자 폭으로 줄을 나눈다. 어절(공백) 단위로 끊고, 한 어절이 너무 길면 글자 단위로 끊는다.
    사용자가 넣은 줄바꿈(\\n)은 항상 유지한다."""
    flags = _char_flags(text, spans)
    lines: list[list[tuple[str, bool]]] = []
    pos = 0
    for para in text.split("\n"):
        pchars = [(para[i], flags[pos + i]) for i in range(len(para))]
        pos += len(para) + 1
        # 어절 토큰: 단어 + 뒤따르는 공백
        tokens: list[list[tuple[str, bool]]] = []
        cur: list[tuple[str, bool]] = []
        for ch in pchars:
            if ch[0] == " " and cur and cur[-1][0] != " ":
                cur.append(ch)
                tokens.append(cur)
                cur = []
            elif ch[0] == " " and not cur:
                if tokens:
                    tokens[-1].append(ch)
            else:
                cur.append(ch)
        if cur:
            tokens.append(cur)
        line: list[tuple[str, bool]] = []
        for tok in tokens:
            candidate = line + tok
            if not line or _measure(_rstrip(candidate), style, emph, size) <= max_w:
                if not line and _measure(_rstrip(tok), style, emph, size) > max_w:
                    # 너무 긴 어절: 글자 단위 분할
                    for ch in tok:
                        if line and _measure(_rstrip(line + [ch]), style, emph, size) > max_w:
                            lines.append(_rstrip(line))
                            line = []
                        line.append(ch)
                    continue
                line = candidate
            else:
                lines.append(_rstrip(line))
                if _measure(_rstrip(tok), style, emph, size) > max_w:
                    line = []
                    for ch in tok:
                        if line and _measure(_rstrip(line + [ch]), style, emph, size) > max_w:
                            lines.append(_rstrip(line))
                            line = []
                        line.append(ch)
                else:
                    line = list(tok)
        lines.append(_rstrip(line))
    return lines


def _rstrip(chars: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    out = list(chars)
    while out and out[-1][0] == " ":
        out.pop()
    return out


# ---------------------------------------------------------------- 텍스트 렌더링

def layout_text(text: str, spans: list[list[int]] | None, style: dict[str, Any], emph: dict[str, Any] | None = None) -> dict[str, Any]:
    emph = emph or {}
    box = style["box"]
    max_w = float(box["w"]) - (2 * float(style["bg"]["pad_x"]) if style["bg"].get("enabled") else 0)
    size = int(style["size"])
    min_size = int(style.get("min_size", size))
    max_lines = int(style.get("max_lines") or 0)
    warnings: list[dict[str, str]] = []
    lines = wrap(text, spans, style, emph, size, max_w)
    shrunk = False
    while max_lines and len(lines) > max_lines and style.get("auto_shrink") and size - 2 >= min_size:
        size -= 2
        shrunk = True
        lines = wrap(text, spans, style, emph, size, max_w)
    if shrunk:
        warnings.append({"code": "auto_shrink", "message": f"글자가 넘쳐 크기를 {style['size']}→{size}로 줄였습니다."})
    if max_lines and len(lines) > max_lines:
        warnings.append({"code": "too_many_lines",
                         "message": f"{len(lines)}줄로 최대 {max_lines}줄을 넘습니다. 문장을 나누거나 너비·크기·최대 줄 수를 조정하세요."})
    info, substituted = fonts.resolve(style.get("font"))
    if substituted:
        warnings.append({"code": "font_substituted", "message": f"'{style.get('font')}' 글꼴이 없어 {info['name']}(으)로 대체했습니다."})
    for key in ("regular", "bold"):
        missing = fonts.missing_glyphs(info[key], text)
        if missing:
            warnings.append({"code": "missing_glyph",
                             "message": f"{info['name']}에 없는 글자: {' '.join(missing[:10])} — 다른 글꼴을 선택하세요."})
            break
    return {"lines": lines, "size": size, "warnings": warnings}


def render_text_image(text: str, spans: list[list[int]] | None, style: dict[str, Any],
                      emph: dict[str, Any] | None = None) -> dict[str, Any]:
    """텍스트 요소를 투명 PNG로 렌더링하고 캔버스 좌표를 돌려준다."""
    emph = emph or {}
    lay = layout_text(text, spans, style, emph)
    lines, size = lay["lines"], lay["size"]
    box = style["box"]
    bg = style["bg"]
    pad_x = float(bg["pad_x"]) if bg.get("enabled") else 0.0
    pad_y = float(bg["pad_y"]) if bg.get("enabled") else 0.0
    line_h = size * float(style.get("line_height", 1.25))
    stroke = int(style.get("stroke_width") or 0)
    shadow = style.get("shadow") or {}
    sh_on = bool(shadow.get("enabled"))
    margin = stroke + (int(abs(shadow.get("dx", 0)) + abs(shadow.get("dy", 0)) + 2 * shadow.get("blur", 0)) if sh_on else 0) + 4

    widths = [_measure(ln, style, emph, size) for ln in lines]
    text_h = line_h * len(lines)
    block_w = float(box["w"])
    block_h = text_h + 2 * pad_y
    W = int(round(block_w + 2 * margin))
    H = int(round(block_h + 2 * margin))
    img = Image.new("RGBA", (max(1, W), max(1, H)), (0, 0, 0, 0))

    base_font, _, _ = _font_for(style, False, emph, size)
    ascent, descent = base_font.getmetrics()
    align = style.get("align", "center")

    def line_x(i: int) -> float:
        inner_l, inner_w = margin + pad_x, block_w - 2 * pad_x
        if align == "left":
            return inner_l
        if align == "right":
            return inner_l + inner_w - widths[i]
        return inner_l + (inner_w - widths[i]) / 2

    # 배경
    if bg.get("enabled") and lines and any(widths):
        d = ImageDraw.Draw(img)
        fill = rgba(bg.get("color"), float(bg.get("opacity", 1)))
        radius = int(bg.get("radius", 0))
        if bg.get("mode") == "line":
            for i, w in enumerate(widths):
                if w <= 0:
                    continue
                x0 = line_x(i) - pad_x
                y0 = margin + pad_y + i * line_h - pad_y * 0.5
                d.rounded_rectangle([x0, y0, x0 + w + 2 * pad_x, y0 + line_h + pad_y], radius=radius, fill=fill)
        else:
            maxw = max(widths)
            if align == "left":
                x0 = margin
            elif align == "right":
                x0 = margin + block_w - maxw - 2 * pad_x
            else:
                x0 = margin + (block_w - maxw - 2 * pad_x) / 2
            d.rounded_rectangle([x0, margin, x0 + maxw + 2 * pad_x, margin + block_h], radius=radius, fill=fill)

    def draw_lines(target: Image.Image, dx: float, dy: float, color_override: tuple | None, with_stroke: bool) -> None:
        d = ImageDraw.Draw(target)
        ls = float(style.get("letter_spacing", 0))
        for i, ln in enumerate(lines):
            x = line_x(i) + dx
            baseline = margin + pad_y + i * line_h + (line_h + ascent - descent) / 2 + dy
            for run_text, f in _runs(ln):
                font, _, _ = _font_for(style, f, emph, size)
                if color_override is not None:
                    fill = color_override
                else:
                    fill = rgba(emph.get("color") if f and emph.get("color") else style.get("color"))
                if f and emph.get("bg_enabled") and color_override is None:
                    rw = (sum(font.getlength(c) for c in run_text) + ls * len(run_text)) if ls else font.getlength(run_text)
                    d.rectangle([x - 4, baseline - ascent, x + rw + 4, baseline + descent], fill=rgba(emph.get("bg_color")))
                kwargs = {}
                if with_stroke and stroke:
                    kwargs = {"stroke_width": stroke, "stroke_fill": rgba(style.get("stroke_color"))}
                if ls:
                    for ch in run_text:
                        d.text((x, baseline), ch, font=font, fill=fill, anchor="ls", **kwargs)
                        x += font.getlength(ch) + ls
                else:
                    d.text((x, baseline), run_text, font=font, fill=fill, anchor="ls", **kwargs)
                    x += font.getlength(run_text)

    if sh_on:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw_lines(layer, float(shadow.get("dx", 0)), float(shadow.get("dy", 0)),
                   rgba(shadow.get("color"), float(shadow.get("opacity", 0.6))), True)
        if shadow.get("blur"):
            layer = layer.filter(ImageFilter.GaussianBlur(float(shadow["blur"])))
        img = Image.alpha_composite(img, layer)
    draw_lines(img, 0, 0, None, True)

    anchor = style.get("anchor_y", "top")
    if anchor == "bottom":
        top = float(box["y"]) - block_h
    elif anchor == "center":
        top = float(box["y"]) - block_h / 2
    else:
        top = float(box["y"])
    x = int(round(float(box["x"]) - margin))
    y = int(round(top - margin))
    warnings = list(lay["warnings"])
    if top < 0 or top + block_h > CANVAS_H or box["x"] < 0 or box["x"] + block_w > CANVAS_W:
        warnings.append({"code": "out_of_canvas", "message": "글자 상자가 화면 경계를 벗어납니다. 위치나 너비를 조정하세요."})
    return {
        "image": img, "x": x, "y": y, "w": img.width, "h": img.height,
        "text_box": {"x": float(box["x"]), "y": top, "w": block_w, "h": block_h},
        "lines": ["".join(c for c, _ in ln) for ln in lines], "size": size, "warnings": warnings,
    }


# ---------------------------------------------------------------- 캐시된 PNG

def _key(*parts: Any) -> str:
    raw = json.dumps([RENDERER_VERSION, fonts.file_signature(), *parts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def overlay_path(key: str) -> Path:
    return OVERLAY_DIR / f"{key}.png"


def cached_text(text: str, spans: list[list[int]] | None, style: dict, emph: dict | None) -> dict[str, Any]:
    key = _key("text", text, spans or [], style, emph or {})
    meta_path = OVERLAY_DIR / f"{key}.json"
    if meta_path.exists() and overlay_path(key).exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    res = render_text_image(text, spans, style, emph)
    res["image"].save(overlay_path(key))
    meta = {k: v for k, v in res.items() if k != "image"}
    meta["key"] = key
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


# ---------------------------------------------------------------- 영상 배치

def video_placement(vstyle: dict[str, Any], src_w: int, src_h: int) -> dict[str, Any]:
    """원본 프레임을 캔버스에 배치한다.
    contain: 원본(또는 사용자 크롭 영역) 전체가 보이게 상자 안에 맞춤 — 기본값
    cover:   상자를 꽉 채우도록 확대(가장자리 손실)."""
    box = vstyle["box"]
    crop = vstyle.get("crop") or {}
    if crop.get("enabled"):
        cx = max(0.0, min(1.0, float(crop.get("x", 0)))) * src_w
        cy = max(0.0, min(1.0, float(crop.get("y", 0)))) * src_h
        cw = max(0.05, min(1.0, float(crop.get("w", 1)))) * src_w
        ch = max(0.05, min(1.0, float(crop.get("h", 1)))) * src_h
        cw, ch = min(cw, src_w - cx), min(ch, src_h - cy)
    else:
        cx, cy, cw, ch = 0.0, 0.0, float(src_w), float(src_h)
    bw, bh = float(box["w"]), float(box["h"])
    warnings = []
    if vstyle.get("fit") == "cover":
        scale = max(bw / cw, bh / ch)
        vis_w, vis_h = bw / scale, bh / scale
        cx += (cw - vis_w) / 2
        cy += (ch - vis_h) / 2
        cw, ch = vis_w, vis_h
        w, h = bw, bh
        x, y = float(box["x"]), float(box["y"])
        warnings.append({"code": "cover_loss", "message": "확대 배치: 원본 가장자리 일부가 보이지 않습니다."})
    else:
        scale = min(bw / cw, bh / ch)
        w, h = cw * scale, ch * scale
        x = float(box["x"]) + (bw - w) / 2
        y = float(box["y"]) + (bh - h) / 2
    if crop.get("enabled"):
        warnings.append({"code": "crop_loss", "message": "사용자 지정 크롭: 선택 영역 밖의 자료는 출력되지 않습니다."})
    # FFmpeg 스케일은 짝수 크기가 안전하다
    W = max(2, int(round(w / 2)) * 2)
    H = max(2, int(round(h / 2)) * 2)
    X, Y = int(round(x)), int(round(y))
    if X < 0 or Y < 0 or X + W > CANVAS_W or Y + H > CANVAS_H:
        warnings.append({"code": "video_out_of_canvas", "message": "영상 일부가 화면 밖으로 나갑니다."})
    return {
        "x": X, "y": Y, "w": W, "h": H,
        "crop": {"x": int(round(cx)), "y": int(round(cy)), "w": max(2, int(round(cw))), "h": max(2, int(round(ch)))},
        "src_w": src_w, "src_h": src_h, "warnings": warnings,
    }


def _asset_path(asset_id: str | None) -> Path | None:
    if not asset_id:
        return None
    from . import db

    row = db.fetchone("SELECT path FROM assets WHERE id=? AND deleted=0", (asset_id,))
    if not row:
        return None
    p = Path(row["path"])
    return p if p.exists() else None


def build_scene(style: dict[str, Any], title: str, title_spans: list[list[int]] | None, src_w: int, src_h: int) -> dict[str, Any]:
    """배경 PNG, 전경 PNG(가리기·제목·고정문구·로고), 영상 배치를 만든다."""
    style = normalize_style(style)
    video = video_placement(style["video"], src_w, src_h)
    title_meta = None
    fixed_meta = None
    if style["title"].get("enabled") and title.strip():
        title_meta = cached_text(title, title_spans, style["title"], style["emphasis"])
    ft = style.get("fixed_text") or {}
    if ft.get("enabled") and (ft.get("text") or "").strip():
        fixed_meta = cached_text(ft["text"], None, ft, None)
    bg_asset = _asset_path(style["canvas"].get("bg_asset_id"))
    logo = style.get("logo") or {}
    logo_asset = _asset_path(logo.get("asset_id")) if logo.get("enabled") else None
    masks = style["video"].get("masks") or []

    bg_key = _key("bg", style["canvas"], str(bg_asset) if bg_asset else None)
    bg_path = overlay_path(bg_key)
    if not bg_path.exists():
        OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
        bg = Image.new("RGBA", (CANVAS_W, CANVAS_H), rgba(style["canvas"].get("bg_color")))
        if bg_asset:
            with Image.open(bg_asset) as im:
                im = im.convert("RGBA")
                s = max(CANVAS_W / im.width, CANVAS_H / im.height)
                im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
                left, top = (im.width - CANVAS_W) // 2, (im.height - CANVAS_H) // 2
                bg.alpha_composite(im.crop((left, top, left + CANVAS_W, top + CANVAS_H)))
        bg.convert("RGB").save(bg_path)

    fg_key = _key("fg", masks, title_meta and title_meta["key"], title_meta and [title_meta["x"], title_meta["y"]],
                  fixed_meta and fixed_meta["key"], logo, str(logo_asset) if logo_asset else None)
    fg_path = overlay_path(fg_key)
    if not fg_path.exists():
        OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
        fg = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(fg)
        for m in masks:
            d.rectangle([m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"]], fill=rgba(m.get("color", "#000000"), float(m.get("opacity", 1))))
        for meta in (title_meta, fixed_meta):
            if meta:
                with Image.open(overlay_path(meta["key"])) as im:
                    fg.alpha_composite(im.convert("RGBA"), dest=(max(0, meta["x"]), max(0, meta["y"])),
                                       source=(max(0, -meta["x"]), max(0, -meta["y"])))
        if logo_asset:
            with Image.open(logo_asset) as im:
                im = im.convert("RGBA")
                lw = max(8, int(logo.get("w", 160)))
                lh = max(1, int(im.height * lw / im.width))
                im = im.resize((lw, lh), Image.LANCZOS)
                if float(logo.get("opacity", 1)) < 1:
                    alpha = im.getchannel("A").point(lambda a: int(a * float(logo.get("opacity", 1))))
                    im.putalpha(alpha)
                fg.alpha_composite(im, dest=(int(logo.get("x", 0)), int(logo.get("y", 0))))
        fg.save(fg_path)

    warnings = list(video["warnings"])
    if title_meta:
        warnings += [{**w, "element": "title"} for w in title_meta["warnings"]]
    if fixed_meta:
        warnings += [{**w, "element": "fixed_text"} for w in fixed_meta["warnings"]]
    if title_meta and _overlap(title_meta["text_box"], video):
        warnings.append({"code": "overlap", "element": "title", "message": "제목이 영상(자료 화면)을 덮습니다."})
    return {"background": bg_key, "foreground": fg_key, "video": video, "title": title_meta, "fixed_text": fixed_meta,
            "warnings": warnings, "style": style}


def _overlap(a: dict, b: dict) -> bool:
    return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def cue_style(style: dict[str, Any], cue: dict[str, Any]) -> dict[str, Any]:
    base = style["subtitle"]
    if cue.get("style_override"):
        base = deep_merge(base, cue["style_override"])
    return base


def render_cue(style: dict[str, Any], cue: dict[str, Any], video_rect: dict | None = None) -> dict[str, Any]:
    style = normalize_style(style)
    meta = cached_text(cue["text"], cue.get("emphasis"), cue_style(style, cue), style["emphasis"])
    if video_rect and _overlap(meta["text_box"], video_rect):
        meta = {**meta, "warnings": meta["warnings"] + [{"code": "overlap", "message": "자막이 영상(자료 화면)을 덮습니다."}]}
    return meta
