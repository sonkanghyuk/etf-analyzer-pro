"""프로젝트·원본·전사·클립·템플릿 데이터 처리."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from . import config, db, edl, layout, media, subtitles
from .errors import StudioError

HISTORY_LIMIT = 100


# ---------------------------------------------------------------- 템플릿

def ensure_builtin_templates() -> None:
    for tid, name, variant in layout.BUILTIN_TEMPLATES:
        if db.fetchone("SELECT id FROM templates WHERE id=?", (tid,)):
            continue
        t = db.now()
        with db.tx() as c:
            c.execute("INSERT INTO templates(id, name, created_at, updated_at, current_version, builtin) VALUES(?,?,?,?,1,1)",
                      (tid, name, t, t))
            c.execute("INSERT INTO template_versions(id, template_id, version, data_json, created_at) VALUES(?,?,?,?,?)",
                      (db.new_id("tv"), tid, 1, db.dumps(layout.default_style(variant)), t))


def list_templates() -> list[dict]:
    rows = db.fetchall("SELECT * FROM templates WHERE deleted=0 ORDER BY builtin DESC, created_at")
    for r in rows:
        r["data"] = template_data(r["id"], r["current_version"])
    return rows


def get_template(tid: str) -> dict:
    row = db.fetchone("SELECT * FROM templates WHERE id=? AND deleted=0", (tid,))
    if not row:
        raise StudioError("NOT_FOUND", "템플릿")
    row["data"] = template_data(tid, row["current_version"])
    row["versions"] = [v["version"] for v in db.fetchall("SELECT version FROM template_versions WHERE template_id=? ORDER BY version", (tid,))]
    return row


def template_data(tid: str, version: int) -> dict:
    row = db.fetchone("SELECT data_json FROM template_versions WHERE template_id=? AND version=?", (tid, version))
    if not row:
        raise StudioError("NOT_FOUND", f"템플릿 버전 {tid} v{version}")
    return layout.normalize_style(row["data"])


def create_template(name: str, data: dict) -> dict:
    tid = db.new_id("tpl")
    t = db.now()
    data = layout.normalize_style(data)
    with db.tx() as c:
        c.execute("INSERT INTO templates(id, name, created_at, updated_at, current_version, builtin) VALUES(?,?,?,?,1,0)", (tid, name, t, t))
        c.execute("INSERT INTO template_versions(id, template_id, version, data_json, created_at) VALUES(?,?,?,?,?)",
                  (db.new_id("tv"), tid, 1, db.dumps(data), t))
    return get_template(tid)


def update_template(tid: str, *, name: str | None = None, data: dict | None = None) -> dict:
    tpl = get_template(tid)
    with db.tx() as c:
        if name:
            c.execute("UPDATE templates SET name=?, updated_at=? WHERE id=?", (name, db.now(), tid))
        if data is not None:
            v = tpl["current_version"] + 1
            c.execute("INSERT INTO template_versions(id, template_id, version, data_json, created_at) VALUES(?,?,?,?,?)",
                      (db.new_id("tv"), tid, v, db.dumps(layout.normalize_style(data)), db.now()))
            c.execute("UPDATE templates SET current_version=?, updated_at=? WHERE id=?", (v, db.now(), tid))
    return get_template(tid)


def duplicate_template(tid: str, name: str | None = None) -> dict:
    tpl = get_template(tid)
    return create_template(name or f"{tpl['name']} 복사본", tpl["data"])


def delete_template(tid: str) -> None:
    tpl = get_template(tid)
    if tpl["builtin"]:
        raise StudioError("NOT_FOUND", "기본 템플릿은 삭제할 수 없습니다(복제해서 수정하세요)")
    db.execute("UPDATE templates SET deleted=1 WHERE id=?", (tid,))


def diff_paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """a와 b가 다른 잎 경로 목록(예: 'subtitle.size')."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b)):
            out += diff_paths(a.get(k), b.get(k), f"{prefix}.{k}" if prefix else k)
        return out
    return [] if a == b else [prefix]


def _get_path(d: dict, path: str) -> Any:
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set_path(d: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = copy.deepcopy(value)


def clip_modified_keys(clip_data: dict) -> list[str]:
    t = clip_data.get("template") or {}
    if not t.get("id"):
        return []
    try:
        base = template_data(t["id"], t["version"])
    except StudioError:
        return []
    return diff_paths(base, layout.normalize_style(clip_data.get("style")))


def apply_template_to_clip(clip_id: str, tid: str, mode: str = "keep") -> dict:
    """mode='keep': 사용자가 바꾼 항목은 유지, 'overwrite': 템플릿으로 모두 덮어쓰기."""
    clip = get_clip(clip_id)
    tpl = get_template(tid)
    data = copy.deepcopy(clip["data"])
    new_style = copy.deepcopy(tpl["data"])
    kept: list[str] = []
    if mode == "keep":
        for path in clip_modified_keys(data):
            _set_path(new_style, path, _get_path(layout.normalize_style(data["style"]), path))
            kept.append(path)
    data["style"] = new_style
    data["template"] = {"id": tid, "version": tpl["current_version"], "name": tpl["name"]}
    return update_clip(clip_id, data=data, title=None, label=f"템플릿 적용({tpl['name']} v{tpl['current_version']}, {'유지' if mode == 'keep' else '덮어쓰기'})") | {"kept_keys": kept}


# ---------------------------------------------------------------- 프로젝트·원본

def register_source(project_id: str, path: Path, filename: str, owned: bool) -> dict:
    info = media.probe(path)
    media.validate_source(info)
    media.decode_check(path)
    sid = db.new_id("src")
    sha = media.sha256_file(path)
    thumb = media.thumbnail(path, config.CACHE_DIR / "thumbs" / f"{sid}.jpg", min(5000, info["duration_ms"] // 3))
    with db.tx() as c:
        c.execute("INSERT INTO sources(id, project_id, filename, path, owned, sha256, size, duration_ms, width, height, fps, has_audio, "
                  "vcodec, acodec, thumb_path, probe_json, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, project_id, filename, str(path), int(owned), sha, path.stat().st_size, info["duration_ms"], info["width"],
                   info["height"], info["fps"], int(info["has_audio"]), info["vcodec"], info["acodec"], str(thumb) if thumb else None,
                   db.dumps(info), db.now()))
        c.execute("UPDATE projects SET source_id=?, updated_at=? WHERE id=?", (sid, db.now(), project_id))
    return get_source(sid)


def create_project(title: str) -> dict:
    pid = db.new_id("prj")
    t = db.now()
    db.execute("INSERT INTO projects(id, title, created_at, updated_at) VALUES(?,?,?,?)", (pid, title.strip() or "새 프로젝트", t, t))
    return get_project(pid)


def create_project_from_file(title: str, path: Path, filename: str, owned: bool) -> dict:
    proj = create_project(title)
    try:
        register_source(proj["id"], path, filename, owned)
    except Exception:
        db.execute("DELETE FROM projects WHERE id=?", (proj["id"],))
        if owned and path.exists():
            path.unlink()
        raise
    return get_project(proj["id"])


def get_source(sid: str | None) -> dict | None:
    if not sid:
        return None
    return db.fetchone("SELECT * FROM sources WHERE id=?", (sid,))


def get_project(pid: str) -> dict:
    p = db.fetchone("SELECT * FROM projects WHERE id=? AND deleted=0", (pid,))
    if not p:
        raise StudioError("NOT_FOUND", "프로젝트")
    p["source"] = public_source(get_source(p["source_id"]))
    p["clip_count"] = (db.fetchone("SELECT COUNT(*) AS n FROM clips WHERE project_id=? AND deleted=0", (pid,)) or {}).get("n", 0)
    p["artifact_count"] = (db.fetchone("SELECT COUNT(*) AS n FROM artifacts WHERE project_id=? AND deleted=0 AND kind='mp4'", (pid,)) or {}).get("n", 0)
    p["has_transcript"] = bool(p.get("transcript_working_id"))
    return p


def public_source(src: dict | None) -> dict | None:
    if not src:
        return None
    out = {k: v for k, v in src.items() if k not in ("probe",)}
    out["path_display"] = src["path"] if not src["owned"] else f"(앱 보관 사본) {Path(src['path']).name}"
    return out


def list_projects(q: str | None = None) -> list[dict]:
    rows = db.fetchall("SELECT id FROM projects WHERE deleted=0 ORDER BY updated_at DESC")
    out = [get_project(r["id"]) for r in rows]
    if q:
        ql = q.lower()
        out = [p for p in out if ql in p["title"].lower() or (p["source"] and ql in (p["source"]["filename"] or "").lower())]
    return out


def rename_project(pid: str, title: str) -> dict:
    get_project(pid)
    db.execute("UPDATE projects SET title=?, updated_at=? WHERE id=?", (title.strip() or "제목 없음", db.now(), pid))
    return get_project(pid)


def touch_project(pid: str) -> None:
    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))


def duplicate_project(pid: str) -> dict:
    p = get_project(pid)
    new = create_project(p["title"] + " 복사본")
    id_map: dict[str, str] = {}
    with db.tx() as c:
        if p["source_id"]:
            c.execute("UPDATE projects SET source_id=? WHERE id=?", (p["source_id"], new["id"]))
        for tr in c.execute("SELECT * FROM transcripts WHERE project_id=?", (pid,)).fetchall():
            nid = db.new_id("tr")
            id_map[tr["id"]] = nid
            c.execute("INSERT INTO transcripts(id, project_id, kind, origin, engine, model, parent_id, version, cues_json, content_hash, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (nid, new["id"], tr["kind"], tr["origin"], tr["engine"], tr["model"], tr["parent_id"], tr["version"], tr["cues_json"],
                       tr["content_hash"], db.now()))
        c.execute("UPDATE projects SET transcript_original_id=?, transcript_working_id=?, analysis_status=? WHERE id=?",
                  (id_map.get(p["transcript_original_id"]), id_map.get(p["transcript_working_id"]), p["analysis_status"], new["id"]))
        for cl in c.execute("SELECT * FROM clips WHERE project_id=? AND deleted=0", (pid,)).fetchall():
            c.execute("INSERT INTO clips(id, project_id, idx, title, data_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                      (db.new_id("clip"), new["id"], cl["idx"], cl["title"], cl["data_json"], db.now(), db.now()))
    return get_project(new["id"])


def delete_project(pid: str, delete_source_copy: bool = False) -> dict:
    """프로젝트 데이터만 숨긴다. 사용자 원본(외부 경로)은 절대 지우지 않는다.
    delete_source_copy=True이고 앱이 복사해 둔 사본이며 다른 프로젝트가 쓰지 않을 때만 사본을 지운다."""
    p = get_project(pid)
    db.execute("UPDATE projects SET deleted=1 WHERE id=?", (pid,))
    removed = False
    src = get_source(p["source_id"])
    if delete_source_copy and src and src["owned"]:
        others = db.fetchone("SELECT COUNT(*) AS n FROM projects WHERE source_id=? AND deleted=0", (src["id"],))
        if not others or others["n"] == 0:
            path = Path(src["path"])
            if path.exists() and config.SOURCES_DIR in path.resolve().parents:
                path.unlink()
                removed = True
    return {"deleted": True, "source_copy_removed": removed}


# ---------------------------------------------------------------- 전사

def _cue_hash(cues: list[dict]) -> str:
    raw = json.dumps([[c["start_ms"], c["end_ms"], c["text"]] for c in cues], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def save_transcript(pid: str, cues: list[dict], origin: str, engine: str | None = None, model: str | None = None,
                    as_original: bool = True) -> dict:
    """새 원문 보존본 + 작업본을 만든다(SRT 불러오기, 자동 전사, 수동 입력)."""
    p = get_project(pid)
    with db.tx() as c:
        orig_id = None
        if as_original:
            orig_id = db.new_id("tr")
            c.execute("INSERT INTO transcripts(id, project_id, kind, origin, engine, model, parent_id, version, cues_json, content_hash, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (orig_id, pid, "original", origin, engine, model, None, 1, db.dumps(cues), _cue_hash(cues), db.now()))
        work_id = db.new_id("tr")
        c.execute("INSERT INTO transcripts(id, project_id, kind, origin, engine, model, parent_id, version, cues_json, content_hash, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (work_id, pid, "working", origin, engine, model, orig_id, 1, db.dumps(cues), _cue_hash(cues), db.now()))
        c.execute("UPDATE projects SET transcript_original_id=COALESCE(?, transcript_original_id), transcript_working_id=?, "
                  "analysis_status='transcribed', updated_at=? WHERE id=?", (orig_id, work_id, db.now(), pid))
    _ = p
    return get_transcript(work_id)


def get_transcript(tid: str | None) -> dict | None:
    if not tid:
        return None
    return db.fetchone("SELECT * FROM transcripts WHERE id=?", (tid,))


def update_working_transcript(pid: str, cues: list[dict]) -> dict:
    """작업본 교정. 새 버전으로 저장하고 원문 보존본은 그대로 둔다."""
    p = get_project(pid)
    cur = get_transcript(p["transcript_working_id"])
    if not cur:
        raise StudioError("NOT_FOUND", "전사 작업본")
    dur = (p["source"] or {}).get("duration_ms") or 10**12
    clean = []
    for c in cues:
        a, b = int(c["start_ms"]), int(c["end_ms"])
        if b <= a or a < 0 or a > dur:
            raise StudioError("SUBTITLE_PARSE", f"잘못된 시각: {c.get('text', '')[:20]}")
        clean.append({"id": c.get("id") or subtitles.new_cue_id(), "start_ms": a, "end_ms": min(b, dur), "text": str(c.get("text", "")),
                      "flags": c.get("flags") or [], **({"words": c["words"]} if c.get("words") else {}),
                      **({"conf": c["conf"]} if c.get("conf") is not None else {})})
    clean.sort(key=lambda x: x["start_ms"])
    h = _cue_hash(clean)
    if h == cur["content_hash"]:
        return cur
    nid = db.new_id("tr")
    with db.tx() as c:
        c.execute("INSERT INTO transcripts(id, project_id, kind, origin, engine, model, parent_id, version, cues_json, content_hash, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (nid, pid, "working", cur["origin"], cur["engine"], cur["model"], cur["id"], cur["version"] + 1, db.dumps(clean), h, db.now()))
        c.execute("UPDATE projects SET transcript_working_id=?, updated_at=? WHERE id=?", (nid, db.now(), pid))
    return get_transcript(nid)  # type: ignore[return-value]


# ---------------------------------------------------------------- 클립

def _cues_for_range(pid: str, start: int, end: int) -> list[dict]:
    p = get_project(pid)
    tr = get_transcript(p["transcript_working_id"])
    if not tr:
        return []
    out = []
    for c in tr["cues"]:
        if c["end_ms"] <= start or c["start_ms"] >= end:
            continue
        out.append({"id": subtitles.new_cue_id(), "src_cue_id": c["id"], "start_ms": max(start, c["start_ms"]),
                    "end_ms": min(end, c["end_ms"]), "text": c["text"], "emphasis": [], "style_override": None,
                    "deleted_speech": False})
    return out


def validate_clip_data(pid: str, data: dict) -> dict:
    p = get_project(pid)
    src = p["source"]
    if not src:
        raise StudioError("NOT_FOUND", "원본 영상")
    rng = data.get("range") or {}
    a, b = int(rng.get("start_ms", 0)), int(rng.get("end_ms", 0))
    if a < 0 or b <= a or b > src["duration_ms"]:
        raise StudioError("SUBTITLE_PARSE", f"구간이 원본 범위를 벗어납니다 (0~{src['duration_ms']}ms)")
    data["range"] = {"start_ms": a, "end_ms": b}
    s = float(data.get("speed") or 1.0)
    if not (edl.SPEED_MIN <= s <= edl.SPEED_MAX):
        raise StudioError("SUBTITLE_PARSE", f"배속은 {edl.SPEED_MIN}~{edl.SPEED_MAX} 범위여야 합니다")
    data["speed"] = s
    cuts = []
    for c in data.get("cuts") or []:
        ca, cb = int(c["start_ms"]), int(c["end_ms"])
        if cb <= ca:
            continue
        cuts.append({"id": c.get("id") or db.new_id("cut"), "start_ms": ca, "end_ms": cb, "reason": c.get("reason", "manual"),
                     "cue_id": c.get("cue_id"), "enabled": bool(c.get("enabled", True))})
    data["cuts"] = cuts
    for cue in data.get("cues") or []:
        if int(cue["end_ms"]) <= int(cue["start_ms"]):
            raise StudioError("SUBTITLE_PARSE", f"자막 시각 오류: {cue.get('text', '')[:20]}")
        cue.setdefault("emphasis", [])
        cue.setdefault("deleted_speech", False)
    data["style"] = layout.normalize_style(data.get("style"))
    data.setdefault("title_emphasis", [])
    data.setdefault("render", {"audio_mode": "auto"})
    return data


def create_clip(pid: str, *, start_ms: int, end_ms: int, title: str, template_id: str | None = None,
                origin: dict | None = None) -> dict:
    get_project(pid)
    tid = template_id or db.get_setting("default_template", "tpl_builtin_dark")
    try:
        tpl = get_template(tid)
    except StudioError:
        tpl = get_template("tpl_builtin_dark")
    data = {
        "range": {"start_ms": int(start_ms), "end_ms": int(end_ms)},
        "cuts": [], "speed": 1.0,
        "cues": _cues_for_range(pid, int(start_ms), int(end_ms)),
        "title_emphasis": [],
        "style": copy.deepcopy(tpl["data"]),
        "template": {"id": tpl["id"], "version": tpl["current_version"], "name": tpl["name"]},
        "origin": origin or {"type": "manual"},
        "render": {"audio_mode": "auto"},
        "description": (origin or {}).get("summary", ""),
    }
    data = validate_clip_data(pid, data)
    row = db.fetchone("SELECT COALESCE(MAX(idx), 0) AS m FROM clips WHERE project_id=?", (pid,))
    idx = (row["m"] if row else 0) + 1
    cid = db.new_id("clip")
    t = db.now()
    db.execute("INSERT INTO clips(id, project_id, idx, title, data_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
               (cid, pid, idx, title.strip() or f"클립 {idx}", db.dumps(data), t, t))
    touch_project(pid)
    return get_clip(cid)


def get_clip(cid: str) -> dict:
    row = db.fetchone("SELECT * FROM clips WHERE id=? AND deleted=0", (cid,))
    if not row:
        raise StudioError("NOT_FOUND", "클립")
    row["data"]["style"] = layout.normalize_style(row["data"].get("style"))
    row["summary"] = edl.summarize(row["data"])
    row["modified_keys"] = clip_modified_keys(row["data"])
    t = row["data"].get("template") or {}
    if t.get("id"):
        cur = db.fetchone("SELECT current_version, name FROM templates WHERE id=?", (t["id"],))
        row["template_latest_version"] = cur["current_version"] if cur else None
    row["undo_count"] = (db.fetchone("SELECT COUNT(*) AS n FROM clip_history WHERE clip_id=? AND stack='undo'", (cid,)) or {}).get("n", 0)
    row["redo_count"] = (db.fetchone("SELECT COUNT(*) AS n FROM clip_history WHERE clip_id=? AND stack='redo'", (cid,)) or {}).get("n", 0)
    return row


def list_clips(pid: str) -> list[dict]:
    return [get_clip(r["id"]) for r in db.fetchall("SELECT id FROM clips WHERE project_id=? AND deleted=0 ORDER BY idx", (pid,))]


def update_clip(cid: str, *, data: dict | None, title: str | None, label: str = "편집") -> dict:
    cur = get_clip(cid)
    new_data = validate_clip_data(cur["project_id"], copy.deepcopy(data if data is not None else cur["data"]))
    new_title = cur["title"] if title is None else (title.strip() or cur["title"])
    if db.dumps(new_data) == db.dumps(cur["data"]) and new_title == cur["title"]:
        return cur
    with db.tx() as c:
        c.execute("INSERT INTO clip_history(clip_id, stack, title, data_json, label, created_at) VALUES(?,?,?,?,?,?)",
                  (cid, "undo", cur["title"], db.dumps(cur["data"]), label, db.now()))
        c.execute("DELETE FROM clip_history WHERE clip_id=? AND stack='redo'", (cid,))
        c.execute("DELETE FROM clip_history WHERE clip_id=? AND stack='undo' AND id NOT IN "
                  "(SELECT id FROM clip_history WHERE clip_id=? AND stack='undo' ORDER BY id DESC LIMIT ?)", (cid, cid, HISTORY_LIMIT))
        c.execute("UPDATE clips SET data_json=?, title=?, updated_at=? WHERE id=?", (db.dumps(new_data), new_title, db.now(), cid))
    touch_project(cur["project_id"])
    return get_clip(cid)


def _move_history(cid: str, src_stack: str, dst_stack: str) -> dict:
    cur = get_clip(cid)
    row = db.fetchone("SELECT * FROM clip_history WHERE clip_id=? AND stack=? ORDER BY id DESC LIMIT 1", (cid, src_stack))
    if not row:
        return cur
    with db.tx() as c:
        c.execute("DELETE FROM clip_history WHERE id=?", (row["id"],))
        c.execute("INSERT INTO clip_history(clip_id, stack, title, data_json, label, created_at) VALUES(?,?,?,?,?,?)",
                  (cid, dst_stack, cur["title"], db.dumps(cur["data"]), row["label"], db.now()))
        c.execute("UPDATE clips SET data_json=?, title=?, updated_at=? WHERE id=?", (db.dumps(row["data"]), row["title"], db.now(), cid))
    return get_clip(cid)


def undo_clip(cid: str) -> dict:
    return _move_history(cid, "undo", "redo")


def redo_clip(cid: str) -> dict:
    return _move_history(cid, "redo", "undo")


def delete_clip(cid: str) -> None:
    get_clip(cid)
    db.execute("UPDATE clips SET deleted=1 WHERE id=?", (cid,))


def delete_cue_speech(cid: str, cue_id: str, restore: bool = False) -> dict:
    """자막에 해당하는 실제 발화(영상·음성)를 삭제/복구한다. 텍스트 교정과는 별개 동작."""
    clip = get_clip(cid)
    data = copy.deepcopy(clip["data"])
    cue = next((c for c in data["cues"] if c["id"] == cue_id), None)
    if not cue:
        raise StudioError("NOT_FOUND", "자막")
    if restore:
        data["cuts"] = [c for c in data["cuts"] if c.get("cue_id") != cue_id]
        cue["deleted_speech"] = False
        label = "발화 삭제 되돌리기"
    else:
        if not any(c.get("cue_id") == cue_id for c in data["cuts"]):
            data["cuts"].append({"id": db.new_id("cut"), "start_ms": cue["start_ms"], "end_ms": cue["end_ms"], "reason": "cue",
                                 "cue_id": cue_id, "enabled": True})
        cue["deleted_speech"] = True
        label = "발화 구간 삭제"
    return update_clip(cid, data=data, title=None, label=label)


def reload_cues_from_transcript(cid: str) -> dict:
    clip = get_clip(cid)
    data = copy.deepcopy(clip["data"])
    data["cues"] = _cues_for_range(clip["project_id"], data["range"]["start_ms"], data["range"]["end_ms"])
    data["cuts"] = [c for c in data["cuts"] if c.get("reason") != "cue"]
    return update_clip(cid, data=data, title=None, label="전사문에서 자막 다시 가져오기")


# ---------------------------------------------------------------- 완성 영상

def list_artifacts(pid: str | None = None, kind: str = "mp4") -> list[dict]:
    if pid:
        rows = db.fetchall("SELECT * FROM artifacts WHERE project_id=? AND kind=? AND deleted=0 ORDER BY created_at DESC", (pid, kind))
    else:
        rows = db.fetchall("SELECT * FROM artifacts WHERE kind=? AND deleted=0 ORDER BY created_at DESC", (kind,))
    for r in rows:
        r["exists"] = Path(r["path"]).exists()
        clip = db.fetchone("SELECT title, idx FROM clips WHERE id=?", (r["clip_id"],)) if r["clip_id"] else None
        r["clip_title"] = clip["title"] if clip else None
        proj = db.fetchone("SELECT title FROM projects WHERE id=?", (r["project_id"],))
        r["project_title"] = proj["title"] if proj else None
    return rows


def get_artifact(aid: str) -> dict:
    row = db.fetchone("SELECT * FROM artifacts WHERE id=? AND deleted=0", (aid,))
    if not row:
        raise StudioError("NOT_FOUND", "완성 영상")
    return row


def export_project_json(pid: str) -> dict:
    p = get_project(pid)
    return {
        "format": "johnber-shorts-project", "schema": config.SCHEMA_VERSION, "exported_at": db.now(),
        "project": {k: p[k] for k in ("id", "title", "created_at")},
        "source": {k: (p["source"] or {}).get(k) for k in ("filename", "sha256", "duration_ms", "width", "height", "fps", "has_audio")},
        "transcript_original": (get_transcript(p["transcript_original_id"]) or {}).get("cues"),
        "transcript_working": (get_transcript(p["transcript_working_id"]) or {}).get("cues"),
        "clips": [{"idx": c["idx"], "title": c["title"], "data": c["data"]} for c in list_clips(pid)],
    }


def import_project_json(payload: dict, source_path: Path | None) -> dict:
    if payload.get("format") != "johnber-shorts-project":
        raise StudioError("SUBTITLE_PARSE", "프로젝트 JSON 형식이 아닙니다")
    title = payload.get("project", {}).get("title", "가져온 프로젝트")
    if source_path is None:
        # 같은 해시의 원본이 이미 등록되어 있으면 재사용
        sha = (payload.get("source") or {}).get("sha256")
        src = db.fetchone("SELECT * FROM sources WHERE sha256=? ORDER BY created_at DESC LIMIT 1", (sha,)) if sha else None
        if not src or not Path(src["path"]).exists():
            raise StudioError("NOT_FOUND", "원본 영상을 찾을 수 없습니다. 원본 파일 경로를 함께 지정하세요")
        proj = create_project(title)
        db.execute("UPDATE projects SET source_id=? WHERE id=?", (src["id"], proj["id"]))
    else:
        proj = create_project_from_file(title, source_path, source_path.name, owned=False)
    pid = proj["id"]
    if payload.get("transcript_working"):
        save_transcript(pid, payload.get("transcript_original") or payload["transcript_working"], "import")
        if payload.get("transcript_original"):
            update_working_transcript(pid, payload["transcript_working"])
    for c in payload.get("clips", []):
        data = validate_clip_data(pid, c["data"])
        cid = db.new_id("clip")
        db.execute("INSERT INTO clips(id, project_id, idx, title, data_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                   (cid, pid, c["idx"], c["title"], db.dumps(data), db.now(), db.now()))
    return get_project(pid)


def copy_upload_to_sources(tmp_path: Path, original_name: str) -> Path:
    ext = Path(original_name).suffix.lower() or ".mp4"
    dest = config.SOURCES_DIR / f"{db.new_id('up')}{ext}"
    shutil.move(str(tmp_path), dest)
    return dest
