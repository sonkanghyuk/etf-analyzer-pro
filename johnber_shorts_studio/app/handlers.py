"""작업 처리기: 렌더링·확정 미리보기·ZIP 일괄 저장·무음 감지·전사·AI 추천."""
from __future__ import annotations

import zipfile
from pathlib import Path

from . import config, db, jobs, media, render, services
from .errors import StudioError


def _clip_bundle(clip_id: str) -> tuple[dict, dict, dict]:
    clip = services.get_clip(clip_id)
    project = services.get_project(clip["project_id"])
    source = services.get_source(project["source_id"])
    if not source:
        raise StudioError("NOT_FOUND", "원본")
    return clip, project, source


def _render(job: dict, ctx: jobs.JobContext, preview: bool) -> dict:
    clip, project, source = _clip_bundle(job["clip_id"])
    ctx.progress(0.0, "장면 준비", force=True)
    res = render.render(clip, project, source, preview=preview,
                        on_progress=lambda p: ctx.progress(p, "인코딩"), handle=ctx.handle, log=ctx.log_lines,
                        audio_mode=(clip["data"].get("render") or {}).get("audio_mode", "auto"))
    ctx.progress(1.0, "검사 완료", force=True)
    aid = db.new_id("art")
    meta = {
        "title": clip["title"], "template": clip["data"].get("template"), "expected_ms": res["expected_ms"],
        "thumb": res["thumb"], "srt": res["srt"], "cue_overlays": res["cue_overlays"], "video_rect": res["video_rect"],
        "edl": clip["summary"], "clip_updated_at": clip["updated_at"], "warnings": res["warnings"],
    }
    db.execute("INSERT INTO artifacts(id, project_id, clip_id, job_id, kind, path, filename, size, duration_ms, probe_json, meta_json, created_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (aid, project["id"], clip["id"], job["id"], "preview" if preview else "mp4", res["path"], res["filename"],
                res["size"], res["duration_ms"], db.dumps(res["probe"]), db.dumps(meta), db.now()))
    return {"artifact_id": aid, "filename": res["filename"], "duration_ms": res["duration_ms"], "size": res["size"]}


@jobs.register("render")
def handle_render(job: dict, ctx: jobs.JobContext) -> dict:
    return _render(job, ctx, preview=False)


@jobs.register("preview")
def handle_preview(job: dict, ctx: jobs.JobContext) -> dict:
    return _render(job, ctx, preview=True)


@jobs.register("export_zip")
def handle_zip(job: dict, ctx: jobs.JobContext) -> dict:
    params = job.get("params") or {}
    deps = params.get("depends_on") or []
    project = services.get_project(job["project_id"])
    files: list[tuple[Path, str]] = []
    missing: list[str] = []
    for dep in deps:
        dj = jobs.get(dep)
        if dj and dj["status"] == "succeeded":
            art = services.get_artifact(dj["result"]["artifact_id"])
            files.append((Path(art["path"]), art["filename"]))
        else:
            missing.append(dep)
    for aid in params.get("artifact_ids") or []:
        art = services.get_artifact(aid)
        files.append((Path(art["path"]), art["filename"]))
    if not files:
        raise StudioError("RENDER_FAILED", "묶을 수 있는 완성 영상이 없습니다")
    out_dir = config.OUTPUT_DIR / project["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    zpath = render.unique_path(out_dir, render.safe_filename(project["title"], 40) + "_일괄", ".zip")
    tmp = zpath.with_suffix(".zip.part")
    used: set[str] = set()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
        for i, (p, name) in enumerate(files):
            ctx.check_cancel()
            arc = name
            n = 2
            while arc in used:
                arc = f"{Path(name).stem}_{n}{Path(name).suffix}"
                n += 1
            used.add(arc)
            zf.write(p, arcname=arc)
            srt = p.with_suffix(".srt")
            if srt.exists():
                zf.write(srt, arcname=Path(arc).with_suffix(".srt").name)
            ctx.progress((i + 1) / len(files), f"압축 {i + 1}/{len(files)}")
    tmp.replace(zpath)
    aid = db.new_id("art")
    db.execute("INSERT INTO artifacts(id, project_id, clip_id, job_id, kind, path, filename, size, duration_ms, probe_json, meta_json, created_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (aid, project["id"], None, job["id"], "zip", str(zpath), zpath.name, zpath.stat().st_size, None, None,
                db.dumps({"files": [n for n in sorted(used)], "missing_jobs": missing}), db.now()))
    return {"artifact_id": aid, "filename": zpath.name, "count": len(files), "missing": missing}


@jobs.register("silence")
def handle_silence(job: dict, ctx: jobs.JobContext) -> dict:
    params = job.get("params") or {}
    clip, _project, source = _clip_bundle(job["clip_id"])
    if not source["has_audio"]:
        raise StudioError("MEDIA_INVALID", "음성 트랙이 없어 무음을 감지할 수 없습니다")
    noise = float(params.get("noise_db", -35))
    min_ms = int(params.get("min_ms", 700))
    keep_ms = int(params.get("keep_ms", 150))
    ctx.progress(None, "무음 분석 중", force=True)
    rng = clip["data"]["range"]
    raw = media.detect_silence(Path(source["path"]), rng["start_ms"], rng["end_ms"], noise, min_ms)
    suggestions = []
    for a, b in raw:
        # 단어 첫·끝음절이 잘리지 않도록 앞뒤 여백을 남긴다
        sa = a + keep_ms if a > rng["start_ms"] else a
        sb = b - keep_ms if b < rng["end_ms"] else b
        if sb - sa >= 100:
            suggestions.append({"start_ms": sa, "end_ms": sb, "raw_start_ms": a, "raw_end_ms": b})
    return {"suggestions": suggestions, "settings": {"noise_db": noise, "min_ms": min_ms, "keep_ms": keep_ms},
            "total_ms": sum(s["end_ms"] - s["start_ms"] for s in suggestions)}


@jobs.register("proxy")
def handle_proxy(job: dict, ctx: jobs.JobContext) -> dict:
    """브라우저가 원본 코덱을 재생하지 못할 때 쓰는 저해상도 WebM. 타임스탬프는 원본과 같다(편집·출력에는 쓰지 않음)."""
    project = services.get_project(job["project_id"])
    source = services.get_source(project["source_id"])
    if not source:
        raise StudioError("NOT_FOUND", "원본")
    out = config.CACHE_DIR / "proxies" / f"{source['sha256'][:32]}.webm"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        tmp = out.with_suffix(".part.webm")
        args = ["-i", source["path"], "-vf", "scale=640:-2", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                "-row-mt", "1", "-b:v", "600k"]
        args += (["-c:a", "libopus", "-b:a", "96k"] if source["has_audio"] else ["-an"])
        args += ["-f", "webm", str(tmp)]
        code = media.run_ffmpeg(args, source["duration_ms"], lambda p: ctx.progress(p, "프록시 인코딩"), ctx.handle, ctx.log_lines)
        if ctx.canceled:
            tmp.unlink(missing_ok=True)
            raise StudioError("CANCELED")
        if code != 0:
            tmp.unlink(missing_ok=True)
            raise StudioError("RENDER_FAILED", f"프록시 ffmpeg 종료 코드 {code}")
        tmp.replace(out)
    db.execute("UPDATE sources SET proxy_path=? WHERE id=?", (str(out), source["id"]))
    return {"proxy": out.name}


# 전사·추천 처리기는 각 모듈에서 등록한다
from . import recommend, transcribe  # noqa: E402,F401
