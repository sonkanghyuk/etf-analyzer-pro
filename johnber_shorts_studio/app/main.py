"""로컬 API 서버 (기본 127.0.0.1에만 바인딩)."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import config, db, dictionary, edl, fonts, handlers, jobs, layout, media, recommend, render, services, subtitles, transcribe
from .errors import StudioError

_ = handlers  # 작업 처리기 등록


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    services.ensure_builtin_templates()
    n = jobs.recover_on_startup()
    if n:
        print(f"[복구] 실행 중이던 작업 {n}개를 '중단됨'으로 정리했습니다.")
    jobs.start_workers()
    yield
    jobs.stop_workers()


app = FastAPI(title=config.APP_NAME_EN, lifespan=lifespan)

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0]
    if host not in _ALLOWED_HOSTS and config.HOST in ("127.0.0.1", "localhost"):
        return JSONResponse({"error": {"code": "FORBIDDEN", "message": "로컬 접속만 허용합니다."}}, status_code=403)
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        ohost = re.sub(r"^https?://", "", origin).split(":")[0].split("/")[0]
        if ohost not in _ALLOWED_HOSTS:
            return JSONResponse({"error": {"code": "FORBIDDEN", "message": "다른 사이트에서 온 요청은 거부합니다."}}, status_code=403)
    return await call_next(request)


@app.exception_handler(StudioError)
async def studio_error(_: Request, e: StudioError):
    status = 404 if e.code == "NOT_FOUND" else 400
    return JSONResponse({"error": e.to_dict()}, status_code=status)


def _body(model: dict | None, key: str, default: Any = None) -> Any:
    return (model or {}).get(key, default)


# ---------------------------------------------------------------- 시스템

@app.get("/api/status")
def api_status() -> dict:
    disk = shutil.disk_usage(config.DATA_DIR)
    return {
        "app": config.APP_NAME, "schema_version": db.schema_version(),
        "ffmpeg": {"found": bool(config.ffmpeg_path() and config.ffprobe_path()), "version": media.ffmpeg_version()},
        "transcribe": transcribe.status(), "ai": recommend.status(),
        "data_dir": str(config.DATA_DIR), "output_dir": str(config.OUTPUT_DIR),
        "disk_free_gb": round(disk.free / 1024**3, 1),
        "fonts": fonts.list_fonts(),
        "features": {
            "youtube_import": "준비 중", "music": "준비 중", "transitions": "준비 중", "mosaic": "준비 중",
            "emphasis_animation": "준비 중", "external_stt": "준비 중", "gpu_encode": "준비 중",
        },
    }


@app.get("/api/dictionary")
def get_dictionary() -> dict:
    return {"words": dictionary.words()}


@app.put("/api/dictionary")
def put_dictionary(body: dict) -> dict:
    return {"words": dictionary.set_words(_body(body, "words", []))}


# ---------------------------------------------------------------- 프로젝트

@app.get("/api/projects")
def projects(q: str | None = None) -> list[dict]:
    return services.list_projects(q)


@app.post("/api/projects/upload")
async def upload_project(file: UploadFile = File(...), title: str = Form("")) -> dict:
    config.ensure_dirs()
    name = Path(file.filename or "video.mp4").name
    tmp = config.TMP_DIR / f"upload_{db.new_id('u')}{Path(name).suffix.lower()}"
    size = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = await file.read(4 * 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise StudioError("UPLOAD_TOO_LARGE")
                out.write(chunk)
        dest = services.copy_upload_to_sources(tmp, name)
        return services.create_project_from_file(title or Path(name).stem, dest, name, owned=True)
    except OSError as e:
        if e.errno == 28:
            raise StudioError("DISK_FULL") from e
        raise
    finally:
        if tmp.exists():
            tmp.unlink()


@app.post("/api/projects/from-path")
def project_from_path(body: dict) -> dict:
    """로컬 경로 등록(복사하지 않음). 큰 강의 파일을 그대로 쓰고, 원본은 읽기만 한다."""
    raw = str(_body(body, "path", "")).strip().strip('"')
    p = Path(raw)
    if not raw or not p.is_absolute() or not p.is_file():
        raise StudioError("NOT_FOUND", "파일 경로를 확인하세요(전체 경로 필요)")
    return services.create_project_from_file(_body(body, "title") or p.stem, p, p.name, owned=False)


@app.get("/api/projects/{pid}")
def project(pid: str) -> dict:
    return services.get_project(pid)


@app.patch("/api/projects/{pid}")
def rename_project(pid: str, body: dict) -> dict:
    return services.rename_project(pid, _body(body, "title", ""))


@app.post("/api/projects/{pid}/duplicate")
def dup_project(pid: str) -> dict:
    return services.duplicate_project(pid)


@app.delete("/api/projects/{pid}")
def del_project(pid: str, delete_source_copy: bool = False) -> dict:
    return services.delete_project(pid, delete_source_copy)


@app.get("/api/projects/{pid}/source")
def project_source(pid: str):
    p = services.get_project(pid)
    src = services.get_source(p["source_id"])
    if not src or not Path(src["path"]).exists():
        raise StudioError("NOT_FOUND", "원본 파일")
    return FileResponse(src["path"], media_type="video/mp4")


@app.get("/api/projects/{pid}/thumb")
def project_thumb(pid: str):
    p = services.get_project(pid)
    src = services.get_source(p["source_id"])
    if not src or not src.get("thumb_path") or not Path(src["thumb_path"]).exists():
        raise StudioError("NOT_FOUND", "썸네일")
    return FileResponse(src["thumb_path"], media_type="image/jpeg")


@app.get("/api/projects/{pid}/export.json")
def export_project(pid: str):
    data = services.export_project_json(pid)
    name = render.safe_filename(data["project"]["title"]) + ".jss.json"
    return Response(json.dumps(data, ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": _disposition(name)})


@app.post("/api/projects/import")
async def import_project(file: UploadFile = File(...), source_path: str = Form("")) -> dict:
    payload = json.loads((await file.read()).decode("utf-8"))
    sp = Path(source_path.strip().strip('"')) if source_path.strip() else None
    if sp and not sp.is_file():
        raise StudioError("NOT_FOUND", "원본 파일 경로")
    return services.import_project_json(payload, sp)


# ---------------------------------------------------------------- 전사·자막

@app.post("/api/projects/{pid}/subtitles")
async def import_subtitles(pid: str, file: UploadFile = File(...)) -> dict:
    services.get_project(pid)
    parsed = subtitles.parse_subtitles(await file.read())
    tr = services.save_transcript(pid, parsed["cues"], "srt", None, None)
    return {"transcript": tr, "issues": parsed["issues"], "encoding": parsed["encoding"]}


@app.post("/api/projects/{pid}/subtitles/manual")
def manual_subtitles(pid: str, body: dict) -> dict:
    p = services.get_project(pid)
    cues = subtitles.parse_manual(_body(body, "text", ""), (p["source"] or {}).get("duration_ms"))
    return {"transcript": services.save_transcript(pid, cues, "manual"), "issues": []}


@app.get("/api/projects/{pid}/transcript")
def transcript(pid: str) -> dict:
    p = services.get_project(pid)
    work = services.get_transcript(p["transcript_working_id"])
    orig = services.get_transcript(p["transcript_original_id"])
    return {"working": work, "original_meta": {k: orig[k] for k in ("id", "origin", "engine", "model", "created_at")} if orig else None,
            "original_cues": orig["cues"] if orig else None,
            "suggestions": dictionary.suggestions(work["cues"]) if work else []}


@app.put("/api/projects/{pid}/transcript")
def put_transcript(pid: str, body: dict) -> dict:
    return services.update_working_transcript(pid, _body(body, "cues", []))


@app.get("/api/projects/{pid}/transcript.srt")
def transcript_srt(pid: str, which: str = "working"):
    p = services.get_project(pid)
    tr = services.get_transcript(p["transcript_original_id" if which == "original" else "transcript_working_id"])
    if not tr:
        raise StudioError("NOT_FOUND", "전사문")
    return Response(subtitles.to_srt(tr["cues"]).encode("utf-8-sig"), media_type="application/x-subrip",
                    headers={"Content-Disposition": _disposition(render.safe_filename(p["title"]) + f"_{which}.srt")})


@app.post("/api/projects/{pid}/transcribe")
def start_transcribe(pid: str, body: dict | None = None) -> dict:
    p = services.get_project(pid)
    src = services.get_source(p["source_id"])
    if not src:
        raise StudioError("NOT_FOUND", "원본")
    return jobs.public(jobs.create("transcribe", project_id=pid, params={"force": bool(_body(body, "force"))},
                                   dedupe_key=f"transcribe:{pid}"))  # type: ignore[return-value]


# ---------------------------------------------------------------- 추천

@app.get("/api/projects/{pid}/recommend/estimate")
def rec_estimate(pid: str, min_s: int = 30, max_s: int = 60, count: int = 8) -> dict:
    return recommend.estimate(pid, {"min_s": min_s, "max_s": max_s, "count": count})


@app.post("/api/projects/{pid}/recommend")
def rec_start(pid: str, body: dict | None = None) -> dict:
    if not config.anthropic_key_present():
        raise StudioError("AI_NOT_CONFIGURED")
    p = services.get_project(pid)
    if not p["transcript_working_id"]:
        raise StudioError("NOT_FOUND", "전사문")
    settings = recommend.default_settings(_body(body, "settings"))
    return jobs.public(jobs.create("recommend", project_id=pid, params={"settings": settings, "force": bool(_body(body, "force"))},
                                   dedupe_key=f"recommend:{pid}"))  # type: ignore[return-value]


@app.post("/api/projects/{pid}/rule-candidates")
def rule_candidates(pid: str, body: dict | None = None) -> dict:
    return recommend.rule_candidates(pid, _body(body, "settings"))


@app.get("/api/projects/{pid}/recommendations")
def recommendations(pid: str) -> list[dict]:
    return recommend.get_recommendations(pid)


# ---------------------------------------------------------------- 클립

@app.get("/api/projects/{pid}/clips")
def clips(pid: str) -> list[dict]:
    return services.list_clips(pid)


@app.post("/api/projects/{pid}/clips")
def new_clip(pid: str, body: dict) -> dict:
    return services.create_clip(pid, start_ms=int(_body(body, "start_ms", 0)), end_ms=int(_body(body, "end_ms", 0)),
                                title=_body(body, "title", ""), template_id=_body(body, "template_id"))


@app.post("/api/projects/{pid}/clips/from-candidate")
def clip_from_candidate(pid: str, body: dict) -> dict:
    rec = db.fetchone("SELECT * FROM recommendations WHERE id=? AND project_id=?", (_body(body, "recommendation_id"), pid))
    if not rec:
        raise StudioError("NOT_FOUND", "추천 결과")
    cand = next((c for c in rec["candidates"] if c["rank"] == int(_body(body, "rank", 0))), None)
    if not cand:
        raise StudioError("NOT_FOUND", "후보")
    ti = int(_body(body, "title_index", 0))
    title = cand["titles"][min(ti, len(cand["titles"]) - 1)] if cand["titles"] else ""
    origin = {"type": "ai" if rec["provider"] == recommend.PROVIDER else "rule", "recommendation_id": rec["id"], "rank": cand["rank"],
              "summary": cand.get("summary", ""), "model": rec.get("model"), "cautions": cand.get("cautions", [])}
    return services.create_clip(pid, start_ms=cand["start_ms"], end_ms=cand["end_ms"], title=title,
                                template_id=_body(body, "template_id"), origin=origin)


@app.get("/api/clips/{cid}")
def clip(cid: str) -> dict:
    return services.get_clip(cid)


@app.put("/api/clips/{cid}")
def put_clip(cid: str, body: dict) -> dict:
    return services.update_clip(cid, data=_body(body, "data"), title=_body(body, "title"), label=_body(body, "label", "편집"))


@app.post("/api/clips/{cid}/undo")
def undo(cid: str) -> dict:
    return services.undo_clip(cid)


@app.post("/api/clips/{cid}/redo")
def redo(cid: str) -> dict:
    return services.redo_clip(cid)


@app.delete("/api/clips/{cid}")
def del_clip(cid: str) -> dict:
    services.delete_clip(cid)
    return {"deleted": True}


@app.post("/api/clips/{cid}/cues/{cue_id}/delete-speech")
def delete_speech(cid: str, cue_id: str, body: dict | None = None) -> dict:
    return services.delete_cue_speech(cid, cue_id, restore=bool(_body(body, "restore")))


@app.post("/api/clips/{cid}/reload-cues")
def reload_cues(cid: str) -> dict:
    return services.reload_cues_from_transcript(cid)


def _scene_payload(clip_row: dict, data: dict, title: str) -> dict:
    project = services.get_project(clip_row["project_id"])
    src = project["source"]
    data = services.validate_clip_data(clip_row["project_id"], copy.deepcopy(data))
    scene = layout.build_scene(data["style"], title, data.get("title_emphasis"), src["width"], src["height"])
    segs = edl.kept_segments(data)
    speed = edl.speed_of(data)
    cues = []
    for c in edl.map_cues(data):
        meta = layout.render_cue(scene["style"], c, scene["video"])
        cues.append({"id": c["id"], "url": f"/api/overlay/{meta['key']}.png", "x": meta["x"], "y": meta["y"], "w": meta["w"], "h": meta["h"],
                     "out_start_ms": c["out_start_ms"], "out_end_ms": c["out_end_ms"], "src_start_ms": c["start_ms"], "src_end_ms": c["end_ms"],
                     "lines": meta["lines"], "size": meta["size"], "warnings": meta["warnings"], "text_box": meta["text_box"]})
    return {
        "canvas": {"w": layout.CANVAS_W, "h": layout.CANVAS_H},
        "background_url": f"/api/overlay/{scene['background']}.png",
        "foreground_url": f"/api/overlay/{scene['foreground']}.png",
        "video": scene["video"], "title": scene["title"], "cues": cues,
        "segments": [{"src_start": s.src_start, "dur": s.dur, "edit_start": s.edit_start} for s in segs],
        "speed": speed, "output_ms": edl.edited_duration(segs) / speed, "warnings": scene["warnings"],
        "safe_area": scene["style"].get("safe_area"), "style": scene["style"],
    }


@app.post("/api/clips/{cid}/scene")
def clip_scene(cid: str, body: dict | None = None) -> dict:
    """저장하지 않은 편집 상태도 미리보기할 수 있게 data/title을 받아 장면을 만든다."""
    row = services.get_clip(cid)
    data = _body(body, "data") or row["data"]
    title = _body(body, "title")
    return _scene_payload(row, data, row["title"] if title is None else title)


@app.post("/api/clips/{cid}/silence")
def silence(cid: str, body: dict | None = None) -> dict:
    row = services.get_clip(cid)
    params = {"noise_db": float(_body(body, "noise_db", -35)), "min_ms": int(_body(body, "min_ms", 700)),
              "keep_ms": int(_body(body, "keep_ms", 150))}
    return jobs.public(jobs.create("silence", project_id=row["project_id"], clip_id=cid, params=params,
                                   dedupe_key=f"silence:{cid}:{json.dumps(params, sort_keys=True)}"))  # type: ignore[return-value]


def _render_key(row: dict, kind: str) -> str:
    h = hashlib.sha1((db.dumps(row["data"]) + row["title"]).encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{row['id']}:{h}"


@app.post("/api/clips/{cid}/render")
def render_clip(cid: str, body: dict | None = None) -> dict:
    row = services.get_clip(cid)
    kind = "preview" if _body(body, "preview") else "render"
    return jobs.public(jobs.create(kind, project_id=row["project_id"], clip_id=cid, params={"clip_updated_at": row["updated_at"]},
                                   dedupe_key=_render_key(row, kind)))  # type: ignore[return-value]


@app.post("/api/clips/{cid}/apply-template")
def apply_template(cid: str, body: dict) -> dict:
    return services.apply_template_to_clip(cid, _body(body, "template_id"), _body(body, "mode", "keep"))


@app.post("/api/projects/{pid}/apply-template")
def apply_template_bulk(pid: str, body: dict) -> dict:
    ids = _body(body, "clip_ids") or [c["id"] for c in services.list_clips(pid)]
    results = []
    for cid in ids:
        r = services.apply_template_to_clip(cid, _body(body, "template_id"), _body(body, "mode", "keep"))
        results.append({"clip_id": cid, "kept_keys": r.get("kept_keys", [])})
    return {"applied": results}


@app.get("/api/clips/{cid}/srt")
def clip_srt(cid: str):
    row = services.get_clip(cid)
    cues = [{"start_ms": c["out_start_ms"], "end_ms": c["out_end_ms"], "text": c["text"]} for c in edl.map_cues(row["data"])]
    return Response(subtitles.to_srt(cues).encode("utf-8-sig"), media_type="application/x-subrip",
                    headers={"Content-Disposition": _disposition(render.safe_filename(row["title"]) + ".srt")})


@app.get("/api/clips/{cid}/text")
def clip_text(cid: str):
    row = services.get_clip(cid)
    body = f"제목: {row['title']}\n\n설명:\n{row['data'].get('description', '')}\n"
    return PlainTextResponse(body, headers={"Content-Disposition": _disposition(render.safe_filename(row["title"]) + ".txt")})


# ---------------------------------------------------------------- 내보내기·완성 영상

@app.post("/api/projects/{pid}/batch-export")
def batch_export(pid: str, body: dict) -> dict:
    ids = _body(body, "clip_ids") or []
    if not ids:
        raise StudioError("NOT_FOUND", "선택한 클립이 없습니다")
    render_jobs = []
    for cid in ids:
        row = services.get_clip(cid)
        if row["project_id"] != pid:
            raise StudioError("NOT_FOUND", "클립")
        render_jobs.append(jobs.public(jobs.create("render", project_id=pid, clip_id=cid, params={"clip_updated_at": row["updated_at"]},
                                                   dedupe_key=_render_key(row, "render"))))
    zip_job = None
    if _body(body, "zip", True):
        dep_ids = [j["id"] for j in render_jobs]  # type: ignore[index]
        zip_job = jobs.public(jobs.create("export_zip", project_id=pid, params={"depends_on": dep_ids},
                                          dedupe_key=f"zip:{pid}:{','.join(sorted(dep_ids))}"))
    return {"render_jobs": render_jobs, "zip_job": zip_job}


@app.get("/api/artifacts")
def artifacts(project_id: str | None = None, kind: str = "mp4") -> list[dict]:
    return services.list_artifacts(project_id, kind)


def _disposition(name: str) -> str:
    from urllib.parse import quote

    return f"attachment; filename=\"download{Path(name).suffix}\"; filename*=UTF-8''{quote(name)}"


@app.get("/api/artifacts/{aid}/download")
def download(aid: str):
    art = services.get_artifact(aid)
    p = Path(art["path"])
    if not p.exists():
        raise StudioError("NOT_FOUND", "파일이 삭제되었거나 이동되었습니다")
    mt = "application/zip" if art["kind"] == "zip" else "video/mp4"
    return FileResponse(p, media_type=mt, headers={"Content-Disposition": _disposition(art["filename"])})


@app.get("/api/artifacts/{aid}/file")
def artifact_inline(aid: str):
    art = services.get_artifact(aid)
    return FileResponse(art["path"], media_type="video/mp4")


@app.get("/api/artifacts/{aid}/thumb")
def artifact_thumb(aid: str):
    art = services.get_artifact(aid)
    t = (art.get("meta") or {}).get("thumb")
    if not t or not Path(t).exists():
        raise StudioError("NOT_FOUND", "썸네일")
    return FileResponse(t, media_type="image/jpeg")


@app.get("/api/artifacts/{aid}/srt")
def artifact_srt(aid: str):
    art = services.get_artifact(aid)
    s = (art.get("meta") or {}).get("srt")
    if not s or not Path(s).exists():
        raise StudioError("NOT_FOUND", "SRT")
    return FileResponse(s, media_type="application/x-subrip", headers={"Content-Disposition": _disposition(Path(art["filename"]).stem + ".srt")})


@app.delete("/api/artifacts/{aid}")
def delete_artifact(aid: str) -> dict:
    art = services.get_artifact(aid)
    p = Path(art["path"])
    if p.exists() and config.OUTPUT_DIR in p.resolve().parents:
        for ext in ("", ".srt", ".jpg"):
            q = p if not ext else p.with_suffix(ext)
            if q.exists():
                q.unlink()
    db.execute("UPDATE artifacts SET deleted=1 WHERE id=?", (aid,))
    return {"deleted": True}


# ---------------------------------------------------------------- 작업

@app.get("/api/jobs")
def list_jobs(project_id: str | None = None) -> list[dict]:
    return [jobs.public(j) for j in jobs.list_jobs(project_id)]  # type: ignore[misc]


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict:
    j = jobs.get(jid)
    if not j:
        raise StudioError("NOT_FOUND", "작업")
    out = jobs.public(j)
    out["log"] = config.redact(j.get("log") or "")  # type: ignore[index]
    return out  # type: ignore[return-value]


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str) -> dict:
    return jobs.public(jobs.cancel(jid)) or {}


@app.post("/api/jobs/{jid}/retry")
def retry_job(jid: str) -> dict:
    return jobs.public(jobs.retry(jid)) or {}


# ---------------------------------------------------------------- 템플릿·에셋

@app.get("/api/templates")
def templates() -> list[dict]:
    return services.list_templates()


@app.post("/api/templates")
def create_template(body: dict) -> dict:
    return services.create_template(_body(body, "name", "새 템플릿"), _body(body, "data") or layout.default_style())


@app.get("/api/templates/{tid}")
def get_template(tid: str) -> dict:
    return services.get_template(tid)


@app.put("/api/templates/{tid}")
def put_template(tid: str, body: dict) -> dict:
    tpl = services.get_template(tid)
    if tpl["builtin"] and _body(body, "data") is not None:
        raise StudioError("NOT_FOUND", "기본 템플릿은 수정할 수 없습니다. 복제한 뒤 수정하세요")
    return services.update_template(tid, name=_body(body, "name"), data=_body(body, "data"))


@app.post("/api/templates/{tid}/duplicate")
def dup_template(tid: str, body: dict | None = None) -> dict:
    return services.duplicate_template(tid, _body(body, "name"))


@app.delete("/api/templates/{tid}")
def del_template(tid: str) -> dict:
    services.delete_template(tid)
    return {"deleted": True}


@app.get("/api/templates/{tid}/export")
def export_template(tid: str):
    t = services.get_template(tid)
    payload = {"format": "johnber-shorts-template", "name": t["name"], "version": t["current_version"], "data": t["data"]}
    return Response(json.dumps(payload, ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": _disposition(render.safe_filename(t["name"]) + ".template.json")})


@app.post("/api/templates/import")
async def import_template(file: UploadFile = File(...)) -> dict:
    payload = json.loads((await file.read()).decode("utf-8"))
    if payload.get("format") != "johnber-shorts-template":
        raise StudioError("SUBTITLE_PARSE", "템플릿 JSON 형식이 아닙니다")
    return services.create_template(payload.get("name", "가져온 템플릿"), payload.get("data") or {})


@app.get("/api/templates/{tid}/preview.png")
def template_preview(tid: str, v: int | None = None):
    t = services.get_template(tid)
    data = services.template_data(tid, v or t["current_version"])
    scene = layout.build_scene(data, "제목 미리보기: SOXL · TQQQ 3.07%", None, 1920, 1080)
    img = Image.open(layout.overlay_path(scene["background"])).convert("RGBA")
    vr = scene["video"]
    ph = Image.new("RGBA", (vr["w"], vr["h"]), (70, 90, 110, 255))
    img.alpha_composite(ph, dest=(vr["x"], vr["y"]))
    img.alpha_composite(Image.open(layout.overlay_path(scene["foreground"])).convert("RGBA"))
    cue = layout.render_cue(data, {"text": "일반 자막 예시와 강조 자막 예시", "emphasis": [[10, 15]]})
    cimg = Image.open(layout.overlay_path(cue["key"])).convert("RGBA")
    img.alpha_composite(cimg, dest=(max(0, cue["x"]), max(0, cue["y"])))
    buf = io.BytesIO()
    img.convert("RGB").resize((270, 480), Image.LANCZOS).save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg")


@app.get("/api/overlay/{name}")
def overlay(name: str):
    m = re.fullmatch(r"([0-9a-f]{20})\.png", name)
    if not m:
        raise HTTPException(404)
    p = layout.overlay_path(m.group(1))
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/fonts")
def list_fonts() -> list[dict]:
    return fonts.list_fonts()


@app.get("/api/assets")
def assets() -> list[dict]:
    return db.fetchall("SELECT id, kind, filename, license_note, created_at FROM assets WHERE deleted=0 ORDER BY created_at DESC")


@app.post("/api/assets")
async def upload_asset(file: UploadFile = File(...), kind: str = Form("logo"), license_note: str = Form("")) -> dict:
    if kind not in ("logo", "background", "font"):
        raise StudioError("NOT_FOUND", "지원하지 않는 에셋 종류")
    raw = await file.read()
    name = Path(file.filename or "asset").name
    if kind == "font":
        if Path(name).suffix.lower() not in (".ttf", ".otf"):
            raise StudioError("MEDIA_INVALID", "TTF/OTF 글꼴만 지원합니다")
        dest = config.FONTS_USER_DIR / render.safe_filename(name)
        dest.write_bytes(raw)
        try:
            from PIL import ImageFont

            ImageFont.truetype(str(dest), 20)
        except Exception as e:
            dest.unlink()
            raise StudioError("MEDIA_INVALID", "글꼴 파일을 읽을 수 없습니다") from e
        fonts.refresh()
    else:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                im.verify()
        except Exception as e:
            raise StudioError("MEDIA_INVALID", "이미지 파일(PNG/JPG)을 읽을 수 없습니다") from e
        aid0 = db.new_id("ast")
        dest = config.ASSETS_DIR / f"{aid0}{Path(name).suffix.lower() or '.png'}"
        dest.write_bytes(raw)
    aid = db.new_id("ast")
    db.execute("INSERT INTO assets(id, kind, filename, path, license_note, created_at) VALUES(?,?,?,?,?,?)",
               (aid, kind, name, str(dest), license_note or "사용자 제공 — 이용 조건 미기재", db.now()))
    return {"id": aid, "kind": kind, "filename": name}


@app.get("/api/assets/{aid}/file")
def asset_file(aid: str):
    row = db.fetchone("SELECT * FROM assets WHERE id=? AND deleted=0", (aid,))
    if not row or not Path(row["path"]).exists():
        raise StudioError("NOT_FOUND", "에셋")
    return FileResponse(row["path"])


@app.delete("/api/assets/{aid}")
def delete_asset(aid: str) -> dict:
    db.execute("UPDATE assets SET deleted=1 WHERE id=?", (aid,))
    return {"deleted": True}


@app.post("/api/artifacts/zip")
def zip_artifacts(body: dict) -> dict:
    ids = _body(body, "artifact_ids") or []
    if not ids:
        raise StudioError("NOT_FOUND", "선택한 완성 영상이 없습니다")
    arts = [services.get_artifact(a) for a in ids]
    pid = arts[0]["project_id"]
    return jobs.public(jobs.create("export_zip", project_id=pid, params={"artifact_ids": ids},
                                   dedupe_key=f"zipart:{','.join(sorted(ids))}"))  # type: ignore[return-value]


@app.get("/ui-fonts/{name}")
def ui_font(name: str):
    p = config.BUNDLED_FONTS_DIR / Path(name).name
    if p.suffix.lower() != ".ttf" or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="font/ttf", headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- 정적 파일

STATIC_DIR = config.APP_ROOT / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

