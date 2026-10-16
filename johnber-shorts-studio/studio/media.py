"""Shared Pillow overlays and a CPU FFmpeg renderer for Johnber Shorts Studio.

The preview and exported MP4 use the very same raster text, measured wraps,
coordinates, font fallbacks and EDL. Input paths never enter a shell command.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time as clock
from typing import Callable

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .timeline import duration, mapped_cues, segments, source_time

WIDTH, HEIGHT, FPS = 1080, 1920, 30


class RenderCancelled(RuntimeError):
    pass


def _executable(name: str) -> str:
    configured = os.environ.get(name.upper() + "_PATH")
    result = configured or shutil.which(name)
    if not result:
        raise RuntimeError(f"{name}를 찾을 수 없습니다. FFmpeg 공식 설치 후 PATH를 확인하세요.")
    return result


def _run(args, *, timeout=60):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("영상 검사 시간이 초과되었습니다.") from exc
    except OSError as exc:
        raise RuntimeError("영상 처리 프로그램을 실행할 수 없습니다. FFmpeg 설치와 파일 접근 권한을 확인하세요.") from exc
    if p.returncode:
        detail = p.stderr.decode("utf-8", errors="replace")[-3000:]
        raise RuntimeError(f"영상 처리 실패: {detail}")
    return p


def probe(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ValueError("원본 영상 파일이 없습니다.")
    p = _run([_executable("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    try:
        data = json.loads(p.stdout)
        videos = [s for s in data["streams"] if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
        if not videos:
            raise ValueError("영상 스트림이 없습니다.")
        video = videos[0]
        fraction = video.get("avg_frame_rate", "0/1").split("/")
        fps = float(fraction[0]) / float(fraction[1]) if len(fraction) == 2 and float(fraction[1]) else 0
        length = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
        if not math.isfinite(length) or length <= 0:
            raise ValueError("영상 길이를 확인할 수 없습니다.")
        return {"duration": length, "width": int(video["width"]), "height": int(video["height"]),
                "fps": fps, "has_audio": any(s.get("codec_type") == "audio" for s in data["streams"]),
                "video_codec": video.get("codec_name"), "pixel_format": video.get("pix_fmt"),
                "audio_codec": next((s.get("codec_name") for s in data["streams"] if s.get("codec_type") == "audio"), None)}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("손상되었거나 지원하지 않는 영상입니다. 실제 MP4/MOV 파일을 선택하세요.") from exc


def default_style(theme: str = "dark") -> dict:
    light = theme == "light"
    fg, bg = ("#14243a", "#f5f3ed") if light else ("#ffffff", "#111827")
    base = {"font": "sans", "weight": "bold", "size": 60, "color": fg,
            "align": "center", "line_height": 1.28, "letter_spacing": 0,
            "outline_width": 0 if light else 3, "outline_color": "#000000",
            "background": "#ffffff" if light else "#000000", "background_opacity": 0,
            "padding": 18, "radius": 18, "shadow": False, "shadow_color": "#000000"}
    result = {"version": 1, "theme": theme, "background": bg,
              "video": {"x": 0, "y": 540, "w": 1080, "h": 608, "fit": "contain"},
              "title": dict(base, x=60, y=110, w=960, h=330, size=78),
              "subtitle": dict(base, x=60, y=1270, w=960, h=430, size=60, background_opacity=0.0),
              "highlight": {"font": "sans", "weight": "bold", "size": 64, "color": "#ffd166", "outline_width": 3, "outline_color": "#000000"},
              "logo": dict(base, x=60, y=1790, w=960, h=90, size=28, color="#8c9aad", text="", outline_width=0)}
    if light:
        result["highlight"].update(color="#b45309", outline_width=0)
    if theme == "minimal":
        result["background"] = "#080b10"
        result["video"].update(y=430, h=810)
        result["title"].update(y=100, h=270, size=64)
        result["subtitle"].update(y=1320, h=340, size=56)
        result["highlight"].update(color="#70e1cf", size=60)
    # Public/template schema uses short keys shared with the visual editor.
    for part in ("title", "subtitle", "highlight", "logo"):
        block = result[part]
        for old, new in (("background", "bg"), ("background_opacity", "bg_opacity"), ("outline_width", "stroke"), ("outline_color", "stroke_color")):
            if old in block:
                block[new] = block.pop(old)
        if "weight" in block:
            block["bold"] = block.pop("weight") == "bold"
    return result


def _aliases(value):
    value = dict(value)
    aliases = {"bg": "background", "bg_opacity": "background_opacity", "stroke": "outline_width", "stroke_color": "outline_color"}
    for old, new in aliases.items():
        if old in value:
            value[new] = value[old]
    if "bold" in value:
        value["weight"] = "bold" if value["bold"] else "normal"
    return value


def _merged_style(style):
    result = default_style((style or {}).get("theme", "dark"))
    for key in ("title", "subtitle", "highlight", "logo"):
        result[key] = _aliases(result[key])
    for key, value in (style or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(_aliases(value))
        else:
            result[key] = copy.deepcopy(value)
    rgb = _color(result.get("background", "#111827"))[:3]
    result["background"] = "#%02x%02x%02x" % rgb
    return result


def _num(value, default, lo, hi):
    try:
        n = float(value)
    except (ValueError, TypeError):
        n = default
    if not math.isfinite(n):
        n = default
    return min(hi, max(lo, n))


def _color(value, opacity=1):
    try:
        color = ImageColor.getrgb(str(value))
    except (ValueError, TypeError):
        color = (255, 255, 255)
    return tuple(color[:3]) + (int(255 * _num(opacity, 1, 0, 1)),)


def _geometry(style, *, video=False):
    limits = (2160, 3840) if video else (WIDTH, HEIGHT)
    x = round(_num(style.get("x", 0), 0, -WIDTH * 2, WIDTH * 2))
    y = round(_num(style.get("y", 0), 0, -HEIGHT * 2, HEIGHT * 2))
    w = round(_num(style.get("w", WIDTH), WIDTH, 20, limits[0]))
    h = round(_num(style.get("h", 400), 400, 20, limits[1]))
    if video:
        w, h = max(2, w // 2 * 2), max(2, h // 2 * 2)
    return x, y, w, h


def _font(style, warnings):
    size = round(_num(style.get("size", 60), 60, 10, 240))
    bold = str(style.get("weight", "bold")) in ("bold", "700", "800", "900")
    serif = style.get("font") == "serif"
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = []
    if serif:
        candidates += [(windows / "batang.ttc", 0), (Path("/usr/share/fonts/opentype/noto") / ("NotoSerifCJK-Bold.ttc" if bold else "NotoSerifCJK-Regular.ttc"), 1)]
    candidates += [(windows / ("malgunbd.ttf" if bold else "malgun.ttf"), 0),
                   (Path("/usr/share/fonts/opentype/noto") / ("NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc"), 1),
                   (Path("/usr/share/fonts/truetype/noto") / ("NotoSansKR-Bold.ttf" if bold else "NotoSansKR-Regular.ttf"), 0)]
    for path, index in candidates:
        if path.is_file():
            try:
                selected = ImageFont.truetype(str(path), size, index=index)
                if serif and "Serif" not in path.name and "batang" not in path.name.lower():
                    warnings.append("바탕계열 한글 글꼴이 없어 고딕계열로 대체했습니다. 선택된 실제 글꼴을 확인하세요.")
                return selected
            except OSError:
                pass
    fallback = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    warnings.append("한글 글꼴이 없습니다. Windows 맑은 고딕 또는 공개 Noto CJK 글꼴을 설치하세요. 현재 대체 글꼴에서는 한글이 누락될 수 있습니다.")
    if fallback.is_file():
        return ImageFont.truetype(str(fallback), size)
    return ImageFont.load_default(size=size)


def _highlight_ranges(text, highlight):
    terms = highlight if isinstance(highlight, list) else [highlight]
    found = set()
    for term in terms:
        if not isinstance(term, str) or not term:
            continue
        start = 0
        while True:
            position = text.find(term, start)
            if position < 0:
                break
            found.update(range(position, position + len(term)))
            start = position + max(1, len(term))
    return found


def _text_layer(text, style, highlight_style, highlight, warnings, label):
    """Pillow is the single authority for preview AND export typography."""
    text = str(text or "")[:12000].replace("\r\n", "\n").replace("\r", "\n")
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if not text or style.get("enabled") is False:
        return canvas
    x, y, w, h = _geometry(style)
    if x < 0 or y < 0 or x + w > WIDTH or y + h > HEIGHT:
        warnings.append(f"{label} 상자가 출력 화면 경계를 벗어납니다. 위치와 크기를 확인하세요.")
    pad = round(_num(style.get("padding", 18), 18, 0, min(w, h) / 3))
    available = max(1, w - pad * 2)
    highlighted = _highlight_ranges(text, highlight) if (highlight_style or {}).get("enabled", True) else set()
    plain_font = _font(style, warnings)
    emphasis = dict(style)
    emphasis.update(highlight_style or {})
    emphasis_font = _font(emphasis, warnings)
    spacing = _num(style.get("letter_spacing", 0), 0, -5, 40)
    items = []
    for index, character in enumerate(text):
        active_style, font = (emphasis, emphasis_font) if index in highlighted else (style, plain_font)
        advance = max(1, font.getlength(character) + spacing) if character != "\n" else 0
        items.append((character, active_style, font, advance))
    # Wrap words when possible, and fall back to measured glyphs for long Korean
    # or ticker tokens. Manual newlines are never discarded.
    tokens, token = [], []
    for item in items:
        if item[0] == "\n":
            if token:
                tokens.append(token)
                token = []
            tokens.append([item])
        elif item[0].isspace():
            if token:
                tokens.append(token)
                token = []
            tokens.append([item])
        else:
            token.append(item)
    if token:
        tokens.append(token)
    lines, line, line_w = [], [], 0.0
    for token in tokens:
        if token[0][0] == "\n":
            lines.append(line)
            line, line_w = [], 0.0
            continue
        token_w = sum(item[3] for item in token)
        if line and line_w + token_w > available:
            while line and line[-1][0].isspace():
                line.pop()
            lines.append(line)
            line, line_w = [], 0.0
        for item in token:
            if not line and item[0].isspace():
                continue
            if line and line_w + item[3] > available:
                lines.append(line)
                line, line_w = [], 0.0
            line.append(item)
            line_w += item[3]
    if line or not lines or text.endswith("\n"):
        lines.append(line)
    line_height = _num(style.get("line_height", 1.28), 1.28, 0.6, 3)
    line_heights = [max([getattr(item[2], "size", 60) for item in row] or [plain_font.size]) * line_height for row in lines]
    # Every glyph in a row shares one baseline. Using an ink-top anchor per
    # character would incorrectly raise decimal points, commas and middle dots.
    baselines = [max([item[2].getmetrics()[0] for item in row] or [plain_font.getmetrics()[0]]) for row in lines]
    ink_bottoms = [max([item[2].getbbox(item[0], anchor="ls")[3] for item in row] or [0]) for row in lines]
    content_extent = max(sum(line_heights), sum(line_heights[:-1]) + baselines[-1] + ink_bottoms[-1])
    required_h = math.ceil(content_extent + pad * 2)
    if required_h > h:
        warnings.append(f"{label} 텍스트가 상자 높이를 초과해 잘립니다. 줄바꿈·글자 크기·상자 높이를 조정하세요. ({required_h}px 필요 / {h}px)")
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    bg_alpha = _num(style.get("background_opacity", 0), 0, 0, 1)
    if bg_alpha > 0:
        draw.rounded_rectangle((0, 0, w - 1, min(h, required_h) - 1), radius=round(_num(style.get("radius", 18), 18, 0, 100)), fill=_color(style.get("background", "#000000"), bg_alpha))
    cursor_y = float(pad)
    align = style.get("align", "center")
    for row, row_h, baseline_offset in zip(lines, line_heights, baselines):
        row_width = sum(item[3] for item in row)
        cursor_x = pad if align == "left" else w - pad - row_width if align == "right" else (w - row_width) / 2
        baseline_y = cursor_y + baseline_offset
        for character, active_style, font, advance in row:
            # Normal and differently sized highlighted glyphs all share this
            # baseline, including punctuation and Latin descenders.
            char_y = baseline_y
            stroke = round(_num(active_style.get("outline_width", 0), 0, 0, 20))
            if active_style.get("background_opacity", 0) and active_style is emphasis:
                draw.rectangle((cursor_x, char_y - font.getmetrics()[0], cursor_x + advance, char_y + font.getmetrics()[1]), fill=_color(active_style.get("background", "#000000"), active_style.get("background_opacity", 0)))
            if active_style.get("shadow"):
                draw.text((cursor_x + 3, char_y + 4), character, font=font, anchor="ls", fill=_color(active_style.get("shadow_color", "#000000")), stroke_width=stroke)
            draw.text((cursor_x, char_y), character, font=font, anchor="ls", fill=_color(active_style.get("color", "#ffffff")), stroke_width=stroke, stroke_fill=_color(active_style.get("outline_color", "#000000")))
            cursor_x += advance
        cursor_y += row_h
    canvas.alpha_composite(image, (x, y))
    return canvas


def font_status() -> dict:
    """Report selected system fonts without exposing machine directory paths."""
    result, warnings = {}, []
    for kind in ("sans", "serif"):
        current = []
        font = _font({"font": kind, "size": 30, "weight": "normal"}, current)
        family, face = font.getname()
        result[kind] = {"family": family, "face": face,
                        "file": Path(getattr(font, "path", "system-default")).name,
                        "korean": not any("한글 글꼴이 없습니다" in warning for warning in current),
                        "fallback": bool(current)}
        warnings.extend(current)
    result["warnings"] = sorted(set(warnings))
    return result


def _load_asset(path, label):
    # Only the backend may inject these internal paths after resolving an asset
    # ID inside its private upload directory. Never accept paths from a browser.
    try:
        with Image.open(Path(path)) as asset:
            if asset.width * asset.height > 25_000_000:
                raise ValueError(f"{label} 이미지가 너무 큽니다. 2500만 픽셀 이하로 줄여 주세요.")
            if asset.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError(f"{label}: PNG, JPG, WEBP 이미지를 선택하세요.")
            return ImageOps.exif_transpose(asset).convert("RGBA")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError(f"{label} 이미지를 읽을 수 없습니다. 원본 에셋을 다시 등록해 주세요.") from exc


def _background_canvas(style):
    image = Image.new("RGBA", (WIDTH, HEIGHT), _color(style["background"]))
    if style.get("background_image_path"):
        asset = _load_asset(style["background_image_path"], "배경")
        if style.get("background_image_fit", "cover") == "contain":
            asset = ImageOps.contain(asset, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        else:
            asset = ImageOps.fit(asset, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        image.alpha_composite(asset, ((WIDTH - asset.width) // 2, (HEIGHT - asset.height) // 2))
    return image


def _static_overlay(clip, style, warnings):
    image = _text_layer(clip.get("title", ""), style["title"], {}, "", warnings, "제목")
    logo = style.get("logo", {})
    if logo.get("enabled", True) and logo.get("image_path"):
        x, y, w, h = _geometry(logo)
        if x < 0 or y < 0 or x + w > WIDTH or y + h > HEIGHT:
            warnings.append("로고 상자가 출력 화면 경계를 벗어납니다.")
        asset = ImageOps.contain(_load_asset(logo["image_path"], "로고"), (w, h), Image.Resampling.LANCZOS)
        opacity = _num(logo.get("opacity", 1), 1, 0, 1)
        if opacity < 1:
            asset.putalpha(asset.getchannel("A").point(lambda alpha: round(alpha * opacity)))
        image.alpha_composite(asset, (x + (w - asset.width) // 2, y + (h - asset.height) // 2))
    if logo.get("text"):
        image.alpha_composite(_text_layer(logo["text"], logo, {}, "", warnings, "로고"))
    return image


def _subtitle_overlay(active, style, warnings):
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if len(active) > 1:
        warnings.append("동시에 표시되는 자막이 겹칩니다. 자막 시작·끝 시각을 확인하세요.")
    for cue in active:
        merged = dict(style["subtitle"])
        merged.update(_aliases(cue.get("style") or {}))
        emphasis = dict(style["highlight"])
        emphasis.update(_aliases(cue.get("highlight_style") or {}))
        image.alpha_composite(_text_layer(cue.get("text", ""), merged, emphasis, cue.get("highlight", ""), warnings, "자막"))
    return image


def _frame_index(seconds):
    # FFmpeg receives exact frame-boundary cue changes. Ceil prevents a caption
    # from starting before its source event; maximum timing error is one frame.
    return max(0, math.ceil(float(seconds) * FPS - 1e-7))


def _active_cues(cues, output_time):
    frame = math.floor(max(0, output_time) * FPS + 1e-7)
    return [c for c in cues if _frame_index(c["start"]) <= frame < _frame_index(c["end"])]


def _validate(source, clip):
    meta = probe(source)
    if float(clip.get("end", 0)) > meta["duration"] + 0.1:
        raise ValueError("클립 끝 시각이 원본 영상 길이를 초과합니다.")
    if duration(clip) < 1 / FPS:
        raise ValueError("출력할 영상이 너무 짧거나 모든 구간이 삭제되었습니다.")
    return meta


def _video_geometry(style, warnings):
    geometry = _geometry(style["video"], video=True)
    x, y, w, h = geometry
    if x < 0 or y < 0 or x + w > WIDTH or y + h > HEIGHT:
        warnings.append("영상 상자가 화면 경계를 벗어납니다. 가장자리 자료가 잘릴 수 있습니다.")
    if style["video"].get("fit", "contain") != "contain":
        warnings.append("사용자 지정 확대/크롭 모드: 원본 가장자리 자료가 잘릴 수 있습니다.")
    return geometry


def preview_frame(source: Path, clip: dict, cues: list, dest: Path, time: float = 0) -> dict:
    """Authoritative 1080x1920 PNG. `time` is edited output seconds."""
    source, dest = Path(source), Path(dest)
    meta = _validate(source, clip)
    style, warnings = _merged_style(clip.get("style")), []
    total = duration(clip)
    output_time = min(max(0, float(time)), max(0, total - 1 / FPS))
    output_time = math.floor(output_time * FPS + 1e-7) / FPS
    source_second = min(source_time(clip, output_time), meta["duration"] - 0.001)
    x, y, w, h = _video_geometry(style, warnings)
    fit = style["video"].get("fit", "contain")
    scale = f"scale={w}:{h}:force_original_aspect_ratio={'decrease' if fit == 'contain' else 'increase'}:force_divisible_by=2"
    if fit != "contain":
        scale += f",crop={w}:{h}"
    else:
        scale += f",pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={style['background']}"
    with tempfile.TemporaryDirectory(prefix="johnber-preview-") as temporary:
        frame_path = Path(temporary) / "source.png"
        _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-threads", "2", "-ss", f"{source_second:.9f}", "-i", str(source), "-frames:v", "1", "-vf", scale, "-threads", "2", "-y", str(frame_path)], timeout=90)
        image = _background_canvas(style)
        with Image.open(frame_path) as video:
            image.alpha_composite(video.convert("RGBA"), (x, y))
        image.alpha_composite(_static_overlay(clip, style, warnings))
        if clip.get("subtitles_enabled", True):
            image.alpha_composite(_subtitle_overlay(_active_cues(mapped_cues(clip, cues), output_time), style, warnings))
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(dest, "PNG")
    return {"path": str(dest), "time": output_time, "source_time": source_second, "duration": total,
            "width": WIDTH, "height": HEIGHT, "warnings": sorted(set(warnings))}


def _tempo(speed):
    filters = []
    remaining = speed
    while remaining < 0.5 - 1e-8:
        filters.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2 + 1e-8:
        filters.append("atempo=2.0")
        remaining /= 2
    filters.append(f"atempo={remaining:.9f}")
    return ",".join(filters)


def _escape_concat(path):
    return str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''")


def _subtitle_sequence(clip, cues, style, folder, total, warnings, cancel=None):
    mapped = mapped_cues(clip, cues) if clip.get("subtitles_enabled", True) else []
    end_frame = max(1, math.ceil(total * FPS - 1e-7))
    events = {0, end_frame}
    for cue in mapped:
        events.update((min(end_frame, _frame_index(cue["start"])), min(end_frame, _frame_index(cue["end"]))))
    frames, cache = sorted(events), {}
    lines = ["ffconcat version 1.0"]
    previous = None
    for begin, finish in zip(frames, frames[1:]):
        if cancel is not None and cancel.is_set():
            raise RenderCancelled("자막 준비 작업이 취소되었습니다.")
        if finish <= begin:
            continue
        active = _active_cues(mapped, begin / FPS)
        key = hashlib.sha256(json.dumps(active, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if key not in cache:
            path = folder / f"subtitle_{len(cache):05d}.png"
            _subtitle_overlay(active, style, warnings).save(path, optimize=False)
            cache[key] = path
        path = cache[key]
        lines += [f"file '{_escape_concat(path)}'", "option framerate 30", f"duration {(finish - begin) / FPS:.9f}"]
        previous = path
    if previous is None:
        raise ValueError("출력 타임라인이 비어 있습니다.")
    lines += [f"file '{_escape_concat(previous)}'", "option framerate 30"]
    result = folder / "subtitles.ffconcat"
    result.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def render(source: Path, clip: dict, cues: list, dest: Path, workdir: Path,
           progress: Callable[[float], None] | None = None, cancel: threading.Event | None = None) -> dict:
    """Render to an atomic temporary file, validate streams, then replace dest.

    `progress` receives actual encoder output-time fractions, never elapsed-time
    guesses. Cancellation terminates only this child process, preserves original
    and any previous successful export, and raises RenderCancelled.
    """
    source, dest, workdir = Path(source), Path(dest), Path(workdir)
    meta = _validate(source, clip)
    if cancel is not None and cancel.is_set():
        raise RenderCancelled("렌더링이 취소되었습니다.")
    total, speed = duration(clip), float(clip.get("speed", 1))
    style, warnings = _merged_style(clip.get("style")), []
    workdir.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=workdir) as temporary:
        folder = Path(temporary)
        static = folder / "static.png"
        _static_overlay(clip, style, warnings).save(static)
        background = None
        if style.get("background_image_path"):
            background = folder / "background.png"
            _background_canvas(style).save(background)
        sequence = _subtitle_sequence(clip, cues, style, folder, total, warnings, cancel)
        x, y, w, h = _video_geometry(style, warnings)
        graph = []
        spans = segments(clip)
        # Trim each span from the source, concatenate in source order, then
        # apply speed ONCE. This avoids per-segment atempo padding drift.
        for index, span in enumerate(spans):
            graph.append(f"[0:v:0]trim=start={span['start'] - float(clip['start']):.9f}:end={span['end'] - float(clip['start']):.9f},setpts=PTS-STARTPTS[v{index}]")
            if meta["has_audio"]:
                graph.append(f"[0:a:0]atrim=start={span['start'] - float(clip['start']):.9f}:end={span['end'] - float(clip['start']):.9f},asetpts=PTS-STARTPTS[a{index}]")
        if meta["has_audio"]:
            inputs = "".join(f"[v{i}][a{i}]" for i in range(len(spans)))
            graph.append(f"{inputs}concat=n={len(spans)}:v=1:a=1[editedv][editeda]")
            graph.append(f"[editeda]{_tempo(speed)},aresample=48000,apad,atrim=duration={total:.9f}[outa]")
        else:
            graph.append("".join(f"[v{i}]" for i in range(len(spans))) + f"concat=n={len(spans)}:v=1:a=0[editedv]")
        fit = style["video"].get("fit", "contain")
        scale = f"scale={w}:{h}:force_original_aspect_ratio={'decrease' if fit == 'contain' else 'increase'}:force_divisible_by=2"
        if fit != "contain":
            scale += f",crop={w}:{h}"
        else:
            scale += f",pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={style['background']}"
        canvas_filter = (f"[3:v]loop=loop=-1:size=1:start=0,settb=AVTB,setpts=N/({FPS}*TB),trim=duration={total:.9f}[canvas]" if background else
                         f"color=c={style['background']}:s={WIDTH}x{HEIGHT}:r={FPS}:d={total:.9f}[canvas]")
        graph += [f"[editedv]setpts=PTS/{speed:.9f},{scale},setsar=1[scaled]",
                  canvas_filter,
                  f"[canvas][scaled]overlay=x={x}:y={y}:eof_action=repeat:shortest=0[base]",
                  "[base][1:v]overlay=eof_action=repeat:shortest=0[titled]",
                  f"[titled][2:v]overlay=eof_action=repeat:shortest=0,fps={FPS},format=yuv420p[outv]"]
        graph_path = folder / "filter.txt"
        graph_path.write_text(";\n".join(graph), encoding="utf-8")
        output = dest.with_name(dest.stem + ".partial-" + folder.name + ".mp4")
        args = [_executable("ffmpeg"), "-hide_banner", "-loglevel", "warning", "-nostdin", "-threads", "2", "-filter_complex_threads", "2",
                "-ss", f"{float(clip['start']):.9f}", "-t", f"{float(clip['end']) - float(clip['start']):.9f}", "-i", str(source), "-i", str(static), "-safe", "0", "-f", "concat", "-i", str(sequence)]
        if background:
            args += ["-i", str(background)]
        args += ["-filter_complex_script", str(graph_path), "-map", "[outv]"]
        if meta["has_audio"]:
            args += ["-map", "[outa]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
        else:
            args += ["-an"]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "2",
                 "-r", str(FPS), "-t", f"{total:.9f}", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-y", str(output)]
        logfile = folder / "ffmpeg.log"
        process = None
        try:
            with logfile.open("wb") as log:
                process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", errors="replace")
                last_progress = [0.0]
                reader_errors = []
                def read_progress():
                    try:
                        for line in process.stdout:
                            if line.startswith("out_time_us="):
                                try:
                                    done = float(line.strip().split("=", 1)[1]) / 1_000_000
                                    value = min(0.995, max(last_progress[0], done / total))
                                    last_progress[0] = value
                                    if progress:
                                        progress(value)
                                except ValueError:
                                    pass
                    except Exception as exc:
                        reader_errors.append(str(exc))
                reader = threading.Thread(target=read_progress, daemon=True)
                reader.start()
                while process.poll() is None:
                    if cancel is not None and cancel.wait(0.1):
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        reader.join(timeout=2)
                        raise RenderCancelled("렌더링이 취소되었습니다. 원본과 이전 성공 파일은 보존됩니다.")
                    elif cancel is None:
                        clock.sleep(0.1)
                reader.join(timeout=5)
                if process.returncode:
                    detail = logfile.read_text(encoding="utf-8", errors="replace")[-5000:]
                    if "No space left on device" in detail:
                        raise RuntimeError("저장 공간이 부족합니다. 출력 폴더의 디스크 여유 공간을 확보하세요.")
                    raise RuntimeError("FFmpeg 렌더링 실패: " + detail)
            if cancel is not None and cancel.is_set():
                raise RenderCancelled("렌더링이 취소되었습니다.")
            result = probe(output)
            if result["width"] != WIDTH or result["height"] != HEIGHT or result["video_codec"] != "h264" or result["pixel_format"] != "yuv420p":
                raise RuntimeError("출력 영상의 코덱 또는 해상도 검증에 실패했습니다.")
            if result["has_audio"] != meta["has_audio"] or (meta["has_audio"] and result["audio_codec"] != "aac"):
                raise RuntimeError("출력 음성 트랙 검증에 실패했습니다.")
            if abs(result["duration"] - total) > max(0.15, 2 / FPS):
                raise RuntimeError(f"출력 길이가 예상과 다릅니다: 예상 {total:.3f}초 / 실제 {result['duration']:.3f}초")
            if cancel is not None and cancel.is_set():
                raise RenderCancelled("렌더링이 취소되었습니다. 이전 성공 파일을 보존합니다.")
            os.replace(output, dest)
            if progress:
                progress(1.0)
            result.update(path=str(dest), expected_duration=total, warnings=sorted(set(warnings)), frame_rounding="ceil caption boundaries to 1/30s; EDL uses float seconds")
            return result
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process is not None and process.stdout:
                process.stdout.close()
            output.unlink(missing_ok=True)


def silence_ranges(source: Path, start: float, end: float, threshold: float = -35,
                   min_duration: float = 0.5, padding: float = 0.12, cancel: threading.Event | None = None) -> list[dict]:
    """Return conservative absolute-source removal candidates, without editing."""
    source = Path(source)
    meta = probe(source)
    start, end = float(start), float(end)
    if not 0 <= start < end <= meta["duration"] + 0.1:
        raise ValueError("무음 검사 구간이 원본 범위를 벗어납니다.")
    if not meta["has_audio"]:
        raise ValueError("원본에 음성 트랙이 없어 무음을 검사할 수 없습니다.")
    threshold = _num(threshold, -35, -90, -5)
    min_duration = _num(min_duration, 0.5, 0.1, 30)
    padding = _num(padding, 0.12, 0, 5)
    args = [_executable("ffmpeg"), "-hide_banner", "-nostdin", "-threads", "2", "-ss", f"{start:.6f}", "-t", f"{end-start:.6f}", "-i", str(source), "-vn", "-af", f"silencedetect=noise={threshold}dB:d={min_duration}", "-f", "null", "-"]
    if cancel is not None and cancel.is_set():
        raise RenderCancelled("무음 검사가 취소되었습니다.")
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = clock.monotonic() + max(120, (end - start) * 3)
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise RenderCancelled("무음 검사가 취소되었습니다.")
            if clock.monotonic() > deadline:
                raise RuntimeError("무음 검사 시간이 초과되었습니다.")
            try:
                _, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError("무음 검사 실패: " + stderr.decode("utf-8", errors="replace")[-3000:])
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stderr:
            process.stderr.close()
    log = stderr.decode("utf-8", errors="replace")
    pending, result = None, []
    for kind, stamp in re.findall(r"silence_(start|end):\s*([0-9.+eE-]+)", log):
        value = max(0, float(stamp))
        if kind == "start":
            pending = value
        else:
            a, b = (pending if pending is not None else 0) + padding, value - padding
            if b > a:
                result.append({"start": min(end, start + a), "end": min(end, start + b)})
            pending = None
    if pending is not None:
        a, b = start + pending + padding, end - padding
        if b > a:
            result.append({"start": a, "end": b})
    return [item for item in result if item["end"] > item["start"]]


def source_thumbnail(source: Path, dest: Path) -> dict:
    """Create a bounded original-video thumbnail, independent of any template."""
    source, dest = Path(source), Path(dest)
    info = probe(source)
    second = min(2.0, info["duration"] * 0.1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run([_executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-threads", "2",
          "-ss", f"{second:.9f}", "-i", str(source), "-frames:v", "1",
          "-vf", "scale=640:360:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=640:360:(ow-iw)/2:(oh-ih)/2:color=#111827,setsar=1",
          "-threads", "2", "-y", str(dest)], timeout=90)
    return {"path": str(dest), "width": 640, "height": 360, "source_time": second}
