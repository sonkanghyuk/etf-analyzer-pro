"""장면 → 세그먼트 mp4 → 이어 붙이기 → 로고·자막(ASS)·라우드니스 → final.mp4."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from . import media, templates
from .brand import brand, color, font, font_path

ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30"]
# 템플릿·디자인 토큰이 바뀌면 캐시된 장면을 다시 렌더한다
CODE_VER = hashlib.sha1(b"".join((templates.PKG / f).read_bytes() for f in ("templates.py", "brand.yaml", "compose.py"))).hexdigest()[:8]


def _src(ep: Path, meta: dict) -> Path:
    p = Path(meta["source"])
    return p if p.is_absolute() else (ep / p)


def logo_png(ep: Path, meta: dict, out: Path) -> Path:
    x0, y0, x1, y1 = brand()["layout"]["logo"]
    bw, bh = x1 - x0, y1 - y0
    cand = [ep / meta["logo"]] if meta.get("logo") else []
    cand.append(templates.PKG / "assets" / "logo.png")
    src = next((c for c in cand if c.exists()), None)
    if src:
        im = Image.open(src).convert("RGBA")
        s = min(bw / im.width, bh / im.height)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    else:  # 임시 텍스트 로고 — assets/logo.png 를 넣으면 대체된다
        im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((3, 10, bw - 3, bh - 10), 18, fill=(255, 255, 255, 230), outline=color("ink"), width=5)
        d.text((bw / 2, bh / 2), "존버나드TV", font=font("bold", 44), fill=color("ink"), anchor="mm")
    canvas = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    canvas.paste(im, ((bw - im.width) // 2, (bh - im.height) // 2), im)
    canvas.save(out)
    return out


def frame_ranges(scenes: list[dict], duration: float, fps: int) -> list[tuple[int, int]]:
    starts = [round(s["at"] * fps) for s in scenes] + [round(duration * fps)]
    return [(a, b) for a, b in zip(starts, starts[1:])]


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]


def state_spans(scene: dict, f0: int, f1: int, n_states: int, fps: int) -> list[tuple[int, int]]:
    cuts = [min(max(round(c * fps), f0 + 1), f1 - 1) for c in scene["cues"][: n_states - 1]]
    edges = [f0] + sorted(cuts) + [f1]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b > a]


def _vf_fill() -> str:
    return "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30"


def render_scene(ep: Path, work: Path, src: Path, info: dict, scene: dict, f0: int, f1: int, meta: dict) -> Path:
    fps = brand()["canvas"]["fps"]
    n = f1 - f0
    kind, p = scene["kind"], {**scene["params"], "_dir": ep}
    if kind == "video" and not info["has_video"]:
        kind, p = "paper", {**p, "title": p.get("title") or scene["chapter"] or meta.get("title", "")}
    out = work / f"seg_{f0:07d}_{_key(kind, p, scene['cues'], f0, f1, str(src), CODE_VER)}.mp4"
    if out.exists():
        return out
    t0 = f0 / fps
    if kind == "video":
        crop, sw, sh = _zoom(p.get("zoom"), info["width"], info["height"])
        fit = p.get("fit") or ("cover" if abs(sw / sh - 16 / 9) < 0.03 else "contain")
        if fit == "cover":
            media.run(["ffmpeg", "-y", "-ss", f"{t0:.3f}", "-i", str(src), "-frames:v", str(n),
                       "-vf", crop + _vf_fill() + ",tpad=stop_mode=clone:stop_duration=2", "-an", *ENC, "-crf", "18",
                       "-preset", "veryfast", str(out)])
        else:  # 16:9가 아닌 녹화(세로 폰·4:3·확대 영역): 종이 배경 위에 그림자와 함께 통째로
            top = 180 if p.get("title") else 40
            bw, bh = 1728, 930 - top
            k = min(bw / sw, bh / sh)
            w2, h2 = int(sw * k) // 2 * 2, int(sh * k) // 2 * 2
            x2, y2 = (W - w2) // 2, top + (bh - h2) // 2
            tmp = work / f"tmp_{out.stem}"
            tmp.mkdir(exist_ok=True)
            bg = _paper_with_shadow(p, (x2, y2, w2, h2), tmp / "bg.png")
            media.run(["ffmpeg", "-y", "-ss", f"{t0:.3f}", "-i", str(src), "-loop", "1", "-i", str(bg), "-filter_complex",
                       f"[0:v]{crop}scale={w2}:{h2},setsar=1,fps=30[v];[1:v][v]overlay={x2}:{y2}:shortest=1,"
                       "format=yuv420p,tpad=stop_mode=clone:stop_duration=2[o]", "-map", "[o]", "-frames:v", str(n),
                       "-an", *ENC, "-crf", "18", "-preset", "veryfast", str(out)])
            shutil.rmtree(tmp, ignore_errors=True)
        return out
    if kind == "broll":
        clip = ep / p["clip"]
        media.run(["ffmpeg", "-y", "-stream_loop", "-1", "-ss", p.get("from", "0"), "-i", str(clip), "-frames:v", str(n),
                   "-vf", _vf_fill(), "-an", *ENC, "-crf", "18", "-preset", "veryfast", str(out)])
        return out
    tpl = templates.get(kind)
    n_items = tpl.n_items(p)
    n_states = min(len(scene["cues"]) + 1, max(1, n_items))
    base_visible = max(1, n_items - (n_states - 1))
    spans = state_spans(scene, f0, f1, n_states, fps)
    tmp = work / f"tmp_{out.stem}"
    tmp.mkdir(exist_ok=True)
    if tpl.kind == "overlay":
        pngs = []
        for i, (a, b) in enumerate(spans):
            fp = tmp / f"s{i}.png"
            tpl.render(p, base_visible + i, 1.0).save(fp)
            pngs.append((fp, (a - f0) / fps, (b - f0) / fps))
        base_in = ["-ss", f"{t0:.3f}", "-i", str(src)] if info["has_video"] else \
            ["-loop", "1", "-i", str(_paper_png(tmp))]
        graph = [f"[0:v]{_vf_fill()},drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill[b0]"]
        for i, (fp, a, b) in enumerate(pngs):
            graph.append(f"[b{i}][{i + 1}:v]overlay=enable='between(t,{a:.3f},{b - 0.001:.3f})'[b{i + 1}]")
        ins = sum((["-i", str(fp)] for fp, _, _ in pngs), [])
        media.run(["ffmpeg", "-y", *base_in, *ins, "-filter_complex", ";".join(graph), "-map", f"[b{len(pngs)}]",
                   "-frames:v", str(n), "-an", *ENC, "-crf", "18", "-preset", "veryfast", str(out)])
    else:
        grow = brand()["motion"]["grow_frames"] if tpl.animated else 0
        lines = []
        for i, (a, b) in enumerate(spans):
            span = b - a
            g = min(grow, max(0, span - 1))
            for j in range(g):
                fp = tmp / f"s{i}_g{j:02d}.png"
                tpl.render(p, base_visible + i, (j + 1) / g).save(fp)
                lines += [f"file '{fp.name}'", f"duration {1 / fps:.6f}"]
            fp = tmp / f"s{i}.png"
            tpl.render(p, base_visible + i, 1.0).save(fp)
            lines += [f"file '{fp.name}'", f"duration {(span - g) / fps:.6f}"]
        lines.append(lines[-2])
        (tmp / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-vf",
                   "fps=30,format=yuv420p,tpad=stop_mode=clone:stop_duration=2", "-frames:v", str(n), *ENC,
                   "-crf", "16", "-preset", "veryfast", str(out.resolve())], cwd=tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


W, H = 1920, 1080


def _zoom(spec: str | None, sw: int, sh: int) -> tuple[str, int, int]:
    """zoom="x,y,w,h" (원본 픽셀 또는 %) → crop 필터와 잘라낸 크기."""
    if not spec:
        return "", sw, sh
    vals = []
    for v, full in zip(str(spec).split(","), (sw, sh, sw, sh)):
        v = v.strip()
        vals.append(int(float(v[:-1]) / 100 * full) if v.endswith("%") else int(float(v)))
    x, y, w, h = vals
    w, h = min(w, sw - x) // 2 * 2, min(h, sh - y) // 2 * 2
    return f"crop={w}:{h}:{x}:{y},", w, h


def _paper_with_shadow(p: dict, box: tuple[int, int, int, int], out: Path) -> Path:
    from PIL import ImageFilter
    img, _ = templates.canvas({"title": p.get("title")})
    x, y, w, h = box
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((x + 10, y + 14, x + w + 10, y + h + 14), fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img.convert("RGBA"), sh.filter(ImageFilter.GaussianBlur(14))).convert("RGB")
    d = ImageDraw.Draw(img)
    templates.credit(d, p.get("credit"))
    img.save(out)
    return out


def _paper_png(tmp: Path) -> Path:
    fp = tmp / "paper.png"
    templates.paper().save(fp)
    return fp


def loudnorm_filter(src: Path, target: float = -14.0) -> str:
    """2패스 라우드니스: 1차로 측정하고 2차에 측정값을 넣어 선형 보정(-14 LUFS, 피크 -1.5 dBTP)."""
    r = media.subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-vn", "-af",
                              f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    try:
        m = json.loads(r[r.rindex("{"): r.rindex("}") + 1])
        return (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    except (ValueError, KeyError):
        return f"loudnorm=I={target}:TP=-1.5:LRA=11"


def render(ep: Path, plan: dict, cues_ass: Path, preview: bool = False, log=print) -> Path:
    media.need()
    meta, scenes = plan["meta"], plan["scenes"]
    src = _src(ep, meta)
    info = media.probe(src)
    fps = brand()["canvas"]["fps"]
    out_dir = ep / "out"
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    ranges = frame_ranges(scenes, info["duration"], fps)
    segs = []
    for k, (sc, (f0, f1)) in enumerate(zip(scenes, ranges)):
        if f1 <= f0:
            continue
        log(f"  장면 {k + 1}/{len(scenes)} {sc['kind']:8s} {f0 / fps:7.1f}s ~ {f1 / fps:7.1f}s")
        segs.append(render_scene(ep, work, src, info, sc, f0, f1, meta))
    (work / "segments.txt").write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "segments.txt", "-c", "copy", "visuals.mp4"], cwd=work)
    # 최종 합성: 상대 경로로 실행해 Windows 경로의 ':' 이스케이프 문제를 피한다
    fonts = out_dir / "fonts"
    fonts.mkdir(exist_ok=True)
    shutil.copy(font_path("subtitle"), fonts / font_path("subtitle").name)
    shutil.copy(cues_ass, out_dir / "subs.ass")
    logo_png(ep, meta, out_dir / "logo.png")
    x0, y0 = brand()["layout"]["logo"][:2]
    final = out_dir / ("preview.mp4" if preview else "final.mp4")
    audio = ["-i", str(src.resolve())] if info["has_audio"] else ["-f", "lavfi", "-t", f"{info['duration']:.3f}", "-i", "anullsrc=r=48000"]
    graph = (f"[0:v][2:v]overlay=x={x0}:y={y0}[v1];[v1]subtitles=subs.ass:fontsdir=fonts[v];"
             f"[1:a]{loudnorm_filter(src) if info['has_audio'] else 'anull'},aresample=48000[a]")
    media.run(["ffmpeg", "-y", "-i", "work/visuals.mp4", *audio, "-i", "logo.png", "-filter_complex", graph,
               "-map", "[v]", "-map", "[a]", *ENC, "-preset", "ultrafast" if preview else "slow",
               "-crf", "26" if preview else "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
               "-shortest", final.name], cwd=out_dir)
    return final
