"""영속 작업 큐. 상태: queued / running / succeeded / failed / canceled / interrupted.

- 작업은 SQLite에 저장되어 브라우저 새로고침·서버 재시작 후에도 상태가 남는다.
- 서버 시작 시 running 상태였던 작업은 interrupted(재시도 가능)로 정리한다.
- 같은 dedupe_key의 대기/실행 작업이 있으면 새 작업을 만들지 않는다(중복 클릭 방지).
- 렌더링 레인과 분석 레인을 분리해 긴 전사가 렌더링을 막지 않게 한다.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Callable

from . import config, db, media
from .errors import StudioError

RENDER_KINDS = {"render", "preview", "export_zip", "silence"}
ANALYSIS_KINDS = {"transcribe", "recommend"}
TERMINAL = {"succeeded", "failed", "canceled", "interrupted"}

Handler = Callable[[dict, "JobContext"], dict | None]
_handlers: dict[str, Handler] = {}
_running: dict[str, "JobContext"] = {}
_wake = threading.Event()
_stop = threading.Event()
_threads: list[threading.Thread] = []


def register(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn
    return deco


class JobContext:
    def __init__(self, job: dict) -> None:
        self.job = job
        self.handle = media.ProcessHandle()
        self.log_lines: list[str] = []
        self._last_write = 0.0
        self.progress_value: float | None = None
        self.stage = ""

    @property
    def canceled(self) -> bool:
        return self.handle.canceled.is_set()

    def check_cancel(self) -> None:
        if self.canceled:
            raise StudioError("CANCELED")

    def progress(self, value: float | None, stage: str | None = None, force: bool = False) -> None:
        self.progress_value = value
        if stage is not None:
            self.stage = stage
        t = time.time()
        if force or t - self._last_write > 0.5:
            self._last_write = t
            db.execute("UPDATE jobs SET progress=?, stage=? WHERE id=?", (value, self.stage, self.job["id"]))

    def log(self, line: str) -> None:
        self.log_lines.append(config.redact(line))


def create(kind: str, *, project_id: str | None = None, clip_id: str | None = None,
           params: dict | None = None, dedupe_key: str | None = None) -> dict:
    with db.tx() as c:
        if dedupe_key:
            row = c.execute("SELECT * FROM jobs WHERE dedupe_key=? AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
                            (dedupe_key,)).fetchone()
            if row:
                d = db.row_to_dict(row)
                d["deduplicated"] = True  # type: ignore[index]
                return d  # type: ignore[return-value]
        jid = db.new_id("job")
        c.execute("INSERT INTO jobs(id, kind, project_id, clip_id, status, progress, stage, created_at, params_json, dedupe_key, log) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (jid, kind, project_id, clip_id, "queued", None, "대기 중", db.now(), db.dumps(params or {}), dedupe_key, ""))
    _wake.set()
    return get(jid)  # type: ignore[return-value]


def get(job_id: str) -> dict | None:
    return db.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))


def list_jobs(project_id: str | None = None, limit: int = 100) -> list[dict]:
    if project_id:
        return db.fetchall("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT ?", (project_id, limit))
    return db.fetchall("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))


def cancel(job_id: str) -> dict | None:
    job = get(job_id)
    if not job:
        return None
    if job["status"] == "queued":
        db.execute("UPDATE jobs SET status='canceled', finished_at=?, error_code='CANCELED', error_message=?, retryable=1 WHERE id=?",
                   (db.now(), "사용자가 작업을 취소했습니다.", job_id))
    elif job["status"] == "running":
        db.execute("UPDATE jobs SET cancel_requested=1, stage='취소 중' WHERE id=?", (job_id,))
        ctx = _running.get(job_id)
        if ctx:
            ctx.handle.cancel()
    return get(job_id)


def retry(job_id: str) -> dict | None:
    job = get(job_id)
    if not job or job["status"] not in ("failed", "canceled", "interrupted"):
        return job
    params = dict(job.get("params") or {})
    params["retry_of"] = job_id
    return create(job["kind"], project_id=job["project_id"], clip_id=job["clip_id"], params=params, dedupe_key=job["dedupe_key"])


def recover_on_startup() -> int:
    with db.tx() as c:
        cur = c.execute("UPDATE jobs SET status='interrupted', finished_at=?, error_code='INTERRUPTED', error_message=?, retryable=1 "
                        "WHERE status='running'", (db.now(), "서버가 재시작되어 작업이 중단되었습니다. 재시도할 수 있습니다."))
        return cur.rowcount


def _deps_ready(job: dict) -> bool:
    deps = (job.get("params") or {}).get("depends_on") or []
    if not deps:
        return True
    rows = db.fetchall(f"SELECT status FROM jobs WHERE id IN ({','.join('?' * len(deps))})", tuple(deps))
    return len(rows) == len(deps) and all(r["status"] in TERMINAL for r in rows)


def _claim(kinds: set[str]) -> dict | None:
    with db.tx() as c:
        rows = c.execute(f"SELECT * FROM jobs WHERE status='queued' AND kind IN ({','.join('?' * len(kinds))}) ORDER BY created_at",
                         tuple(kinds)).fetchall()
    for r in rows:
        job = db.row_to_dict(r)
        if not _deps_ready(job):  # type: ignore[arg-type]
            continue
        with db.tx() as c:
            cur = c.execute("UPDATE jobs SET status='running', started_at=?, stage='시작' WHERE id=? AND status='queued'", (db.now(), job["id"]))  # type: ignore[index]
            if cur.rowcount == 1:
                return get(job["id"])  # type: ignore[index]
    return None


def _run(job: dict) -> None:
    ctx = JobContext(job)
    _running[job["id"]] = ctx
    handler = _handlers.get(job["kind"])
    try:
        if handler is None:
            raise StudioError("INTERNAL", f"알 수 없는 작업 종류 {job['kind']}")
        result = handler(job, ctx) or {}
        if ctx.canceled:
            raise StudioError("CANCELED")
        db.execute("UPDATE jobs SET status='succeeded', progress=1, stage='완료', finished_at=?, result_json=?, log=? WHERE id=?",
                   (db.now(), db.dumps(result), "\n".join(ctx.log_lines[-200:]), job["id"]))
    except StudioError as e:
        status = "canceled" if e.code == "CANCELED" else "failed"
        ctx.log(f"[{e.code}] {e.detail or ''}")
        db.execute("UPDATE jobs SET status=?, finished_at=?, error_code=?, error_message=?, retryable=?, stage=?, log=? WHERE id=?",
                   (status, db.now(), e.code, config.redact(e.message + (f" ({e.detail})" if e.detail else "")), int(e.retryable),
                    "취소됨" if status == "canceled" else "실패", "\n".join(ctx.log_lines[-200:]), job["id"]))
    except OSError as e:
        code = "DISK_FULL" if getattr(e, "errno", None) == 28 else "INTERNAL"
        ctx.log(traceback.format_exc())
        db.execute("UPDATE jobs SET status='failed', finished_at=?, error_code=?, error_message=?, retryable=1, stage='실패', log=? WHERE id=?",
                   (db.now(), code, config.redact(str(e)), "\n".join(ctx.log_lines[-200:]), job["id"]))
    except Exception as e:  # noqa: BLE001
        ctx.log(traceback.format_exc())
        db.execute("UPDATE jobs SET status='failed', finished_at=?, error_code='INTERNAL', error_message=?, retryable=1, stage='실패', log=? WHERE id=?",
                   (db.now(), config.redact(f"{type(e).__name__}: {e}"), "\n".join(ctx.log_lines[-200:]), job["id"]))
    finally:
        _running.pop(job["id"], None)
        _wake.set()


def _lane(kinds: set[str]) -> None:
    while not _stop.is_set():
        job = _claim(kinds)
        if job is None:
            _wake.wait(timeout=1.0)
            _wake.clear()
            continue
        _run(job)


def start_workers() -> None:
    if _threads:
        return
    _stop.clear()
    for name, kinds in (("render", RENDER_KINDS), ("analysis", ANALYSIS_KINDS)):
        t = threading.Thread(target=_lane, args=(kinds,), name=f"jss-{name}", daemon=True)
        t.start()
        _threads.append(t)


def stop_workers() -> None:
    _stop.set()
    _wake.set()
    for ctx in list(_running.values()):
        ctx.handle.cancel()
    for t in _threads:
        t.join(timeout=10)
    _threads.clear()


def wait(job_id: str, timeout: float = 600) -> dict:
    """테스트·CLI용: 작업이 끝날 때까지 기다린다."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = get(job_id)
        if job and job["status"] in TERMINAL:
            return job
        time.sleep(0.2)
    raise TimeoutError(job_id)


def public(job: dict | None) -> dict | None:
    if not job:
        return None
    out = {k: v for k, v in job.items() if k not in ("log",)}
    out["elapsed_s"] = round((job.get("finished_at") or time.time()) - (job.get("started_at") or job.get("created_at") or time.time()), 1) \
        if job.get("started_at") else None
    return out

