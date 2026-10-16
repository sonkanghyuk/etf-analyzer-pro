"""편집 데이터 → 실제 MP4.

미리보기와 같은 장면 데이터(layout.build_scene / render_cue)와 같은 시간 매핑(edl)을 사용한다.
결과는 임시 경로에 쓰고 ffprobe 검사를 통과한 경우에만 완료 폴더로 옮긴다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from . import config, edl, layout, media, subtitles
from .errors import StudioError

AUDIO_RATE = 48000

_WIN_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(name: str, max_len: int = 80) -> str:
    name = _WIN_FORBIDDEN.sub("_", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = "clip"
    if name.upper() in _WIN_RESERVED:
        name = "_" + name
    return name[:max_len].rstrip(" .")


def unique_path(directory: Path, stem: str, ext: str) -> Path:
    p = directory / f"{stem}{ext}"
    n = 2
    while p.exists():
        p = directory / f"{stem}_{n}{ext}"
        n += 1
    return p


def output_filename(project_title: str, idx: int, clip_title: str) -> str:
    return f"{safe_filename(project_title, 40)}_{idx:02d}_{safe_filename(clip_title, 60)}"


def _atempo_chain(speed: float) -> str:
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.6f}")
    return ",".join(parts)


def build_plan(clip: dict[str, Any], source: dict[str, Any], *, fps: int = 30, preview: bool = False,
               audio_mode: str = "auto") -> dict[str, Any]:
    """렌더링에 필요한 모든 수치를 계산한다(테스트에서 직접 검증 가능)."""
    data = clip["data"]
    segs = edl.kept_segments(data, fps)
    if not segs:
        raise StudioError("CLIP_EMPTY")
    speed = edl.speed_of(data)
    out_ms = edl.edited_duration(segs) / speed
    scene = layout.build_scene(data["style"], clip.get("title") or "", data.get("title_emphasis"), source["width"], source["height"])
    cues = edl.map_cues(data, fps)
    cue_overlays = []
    for c in cues:
        meta = layout.render_cue(scene["style"], c, scene["video"])
        cue_overlays.append({"cue_id": c["id"], "key": meta["key"], "x": meta["x"], "y": meta["y"],
                             "start": c["out_start_ms"] / 1000, "end": c["out_end_ms"] / 1000, "lines": meta["lines"]})
    use_audio = bool(source.get("has_audio")) and audio_mode != "silent"
    return {"segments": segs, "speed": speed, "out_ms": out_ms, "scene": scene, "cues": cues,
            "cue_overlays": cue_overlays, "fps": fps, "preview": preview, "use_audio": use_audio}


def build_command(plan: dict[str, Any], source_path: Path, out_path: Path) -> list[str]:
    fps = plan["fps"]
    segs: list[edl.Segment] = plan["segments"]
    scene = plan["scene"]
    v = scene["video"]
    out_s = plan["out_ms"] / 1000
    args: list[str] = []
    for s in segs:
        args += ["-ss", f"{s.src_start / 1000:.3f}", "-t", f"{s.dur / 1000 + 0.5:.3f}", "-i", str(source_path)]
    n = len(segs)
    bg_idx = n
    args += ["-loop", "1", "-framerate", str(fps), "-t", f"{out_s:.3f}", "-i", str(layout.overlay_path(scene["background"]))]
    fg_idx = n + 1
    args += ["-i", str(layout.overlay_path(scene["foreground"]))]
    cue_base = n + 2
    for co in plan["cue_overlays"]:
        args += ["-i", str(layout.overlay_path(co["key"]))]
    silent_idx = None
    if not plan["use_audio"]:
        silent_idx = cue_base + len(plan["cue_overlays"])
        args += ["-f", "lavfi", "-t", f"{out_s:.3f}", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]

    f: list[str] = []
    concat_in = ""
    for i, s in enumerate(segs):
        frames = int(round(s.dur * fps / 1000))
        f.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop_duration=1,"
                 f"trim=end_frame={frames},setpts=PTS-STARTPTS[v{i}]")
        if plan["use_audio"]:
            samples = int(round(s.dur * AUDIO_RATE / 1000))
            f.append(f"[{i}:a]asetpts=PTS-STARTPTS,aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"apad,atrim=end_sample={samples},asetpts=PTS-STARTPTS[a{i}]")
            concat_in += f"[v{i}][a{i}]"
        else:
            concat_in += f"[v{i}]"
    if plan["use_audio"]:
        f.append(f"{concat_in}concat=n={n}:v=1:a=1[vc][ac]")
    else:
        f.append(f"{concat_in}concat=n={n}:v=1:a=0[vc]")
    c = v["crop"]
    speed = plan["speed"]
    vchain = f"[vc]setpts=PTS/{speed:.6f},fps={fps}," if abs(speed - 1) > 1e-6 else "[vc]"
    vchain += f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale={v['w']}:{v['h']}:flags=lanczos,setsar=1[vs]"
    f.append(vchain)
    f.append(f"[{bg_idx}:v]format=rgba[bg]")
    f.append(f"[bg][vs]overlay={v['x']}:{v['y']}:eof_action=repeat[s0]")
    f.append(f"[s0][{fg_idx}:v]overlay=0:0[s1]")
    last = "s1"
    for j, co in enumerate(plan["cue_overlays"]):
        nxt = f"s{j + 2}"
        f.append(f"[{last}][{cue_base + j}:v]overlay={co['x']}:{co['y']}:enable='between(t,{co['start']:.4f},{co['end'] - 0.0005:.4f})'[{nxt}]")
        last = nxt
    if plan["preview"]:
        f.append(f"[{last}]scale=540:960:flags=bicubic,format=yuv420p[vout]")
    else:
        f.append(f"[{last}]format=yuv420p[vout]")
    if plan["use_audio"]:
        achain = "[ac]" + (_atempo_chain(speed) + "," if abs(speed - 1) > 1e-6 else "") + "apad[aout]"
    else:
        achain = f"[{silent_idx}:a]anull[aout]"
    f.append(achain)

    args += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]"]
    if plan["preview"]:
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high"]
    args += ["-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), "-ac", "2",
             "-t", f"{out_s:.3f}", "-movflags", "+faststart", str(out_path)]
    return args


def verify_output(path: Path, expected_ms: float, preview: bool, expect_audio: bool) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 1024:
        raise StudioError("RENDER_INVALID_OUTPUT", "파일이 없거나 비어 있음")
    info = media.probe(path)
    w, h = (540, 960) if preview else (1080, 1920)
    problems = []
    if info.get("vcodec") != "h264":
        problems.append(f"영상 코덱 {info.get('vcodec')}")
    if (info.get("width"), info.get("height")) != (w, h):
        problems.append(f"해상도 {info.get('width')}x{info.get('height')}")
    if info.get("pix_fmt") != "yuv420p":
        problems.append(f"픽셀 형식 {info.get('pix_fmt')}")
    if not info.get("has_audio") or info.get("acodec") != "aac":
        problems.append("오디오 스트림 없음")
    dur = info.get("duration_ms") or 0
    if abs(dur - expected_ms) > max(150, expected_ms * 0.01):
        problems.append(f"길이 {dur}ms (예상 {expected_ms:.0f}ms)")
    if problems:
        raise StudioError("RENDER_INVALID_OUTPUT", ", ".join(problems))
    info["audio_kind"] = "source" if expect_audio else "silent"
    return info


def render(clip: dict[str, Any], project: dict[str, Any], source: dict[str, Any], *, preview: bool,
           on_progress: Callable[[float], None], handle: media.ProcessHandle, log: list[str],
           audio_mode: str = "auto") -> dict[str, Any]:
    media.require_ffmpeg()
    plan = build_plan(clip, source, preview=preview, audio_mode=audio_mode)
    src_path = Path(source["path"])
    if not src_path.exists():
        raise StudioError("NOT_FOUND", f"원본 파일 없음: {src_path.name}")
    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.TMP_DIR / f"{clip['id']}_{os.getpid()}_{int(plan['out_ms'])}{'_pv' if preview else ''}.part.mp4"
    free = shutil.disk_usage(config.TMP_DIR).free
    if free < 300 * 1024 * 1024:
        raise StudioError("DISK_FULL", f"남은 공간 {free // (1024 * 1024)}MB")
    args = build_command(plan, src_path, tmp)
    log.append("ffmpeg " + " ".join(a if " " not in a else f'"{a}"' for a in args)[:4000])
    try:
        code = media.run_ffmpeg(args, int(plan["out_ms"]), on_progress, handle, log)
        if handle.canceled.is_set():
            raise StudioError("CANCELED")
        if code != 0:
            tail = "\n".join(log[-8:])
            if "No space left" in tail:
                raise StudioError("DISK_FULL")
            raise StudioError("RENDER_FAILED", f"ffmpeg 종료 코드 {code}")
        info = verify_output(tmp, plan["out_ms"], preview, plan["use_audio"])
        out_dir = config.OUTPUT_DIR / project["id"] / ("previews" if preview else "")
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = output_filename(project["title"], clip["idx"], clip.get("title") or "clip")
        if preview:
            stem = f"preview_{clip['id']}"
            final = out_dir / f"{stem}.mp4"
            os.replace(tmp, final)
        else:
            final = unique_path(out_dir, stem, ".mp4")
            os.replace(tmp, final)
        srt_path = final.with_suffix(".srt")
        srt_cues = [{"start_ms": c["out_start_ms"], "end_ms": c["out_end_ms"], "text": c["text"]} for c in plan["cues"]]
        srt_path.write_text(subtitles.to_srt(srt_cues), encoding="utf-8-sig")
        thumb = media.thumbnail(final, final.with_suffix(".jpg"), int(min(plan["out_ms"] / 2, 1500)), 270)
        return {
            "path": str(final), "filename": final.name, "size": final.stat().st_size,
            "duration_ms": info["duration_ms"], "probe": info, "thumb": str(thumb) if thumb else None,
            "srt": str(srt_path), "expected_ms": plan["out_ms"],
            "cue_overlays": [{k: v for k, v in co.items()} for co in plan["cue_overlays"]],
            "video_rect": {k: plan["scene"]["video"][k] for k in ("x", "y", "w", "h", "crop")},
            "warnings": plan["scene"]["warnings"],
        }
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def plan_summary(plan: dict[str, Any]) -> str:
    return json.dumps({"segments": len(plan["segments"]), "out_ms": plan["out_ms"], "cues": len(plan["cue_overlays"])})
