"""SQLite 저장소. 스키마 버전과 순차 마이그레이션을 관리한다.

로컬 1인 사용을 전제로 호출마다 짧은 연결을 열고 WAL 모드를 쓴다.
복잡한 편집 상태(클립 EDL·자막·스타일)는 JSON 열에 저장한다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

_lock = threading.RLock()

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at REAL, updated_at REAL,
        source_id TEXT, transcript_original_id TEXT, transcript_working_id TEXT,
        analysis_status TEXT DEFAULT 'none', deleted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sources (
        id TEXT PRIMARY KEY, project_id TEXT, filename TEXT, path TEXT, owned INTEGER,
        sha256 TEXT, size INTEGER, duration_ms INTEGER, width INTEGER, height INTEGER,
        fps REAL, has_audio INTEGER, vcodec TEXT, acodec TEXT, thumb_path TEXT,
        probe_json TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS transcripts (
        id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, origin TEXT, engine TEXT, model TEXT,
        parent_id TEXT, version INTEGER, cues_json TEXT, content_hash TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS clips (
        id TEXT PRIMARY KEY, project_id TEXT, idx INTEGER, title TEXT, data_json TEXT,
        created_at REAL, updated_at REAL, deleted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS clip_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id TEXT, stack TEXT, title TEXT,
        data_json TEXT, label TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS templates (
        id TEXT PRIMARY KEY, name TEXT, created_at REAL, updated_at REAL,
        current_version INTEGER, builtin INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS template_versions (
        id TEXT PRIMARY KEY, template_id TEXT, version INTEGER, data_json TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, kind TEXT, project_id TEXT, clip_id TEXT, status TEXT,
        progress REAL, stage TEXT, created_at REAL, started_at REAL, finished_at REAL,
        error_code TEXT, error_message TEXT, retryable INTEGER DEFAULT 0, log TEXT,
        params_json TEXT, result_json TEXT, dedupe_key TEXT, cancel_requested INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY, project_id TEXT, clip_id TEXT, job_id TEXT, kind TEXT,
        path TEXT, filename TEXT, size INTEGER, duration_ms INTEGER, probe_json TEXT,
        meta_json TEXT, created_at REAL, deleted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS transcribe_cache (
        key TEXT PRIMARY KEY, cues_json TEXT, engine TEXT, model TEXT, info_json TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS recommendations (
        id TEXT PRIMARY KEY, project_id TEXT, transcript_id TEXT, provider TEXT, model TEXT,
        cache_key TEXT, settings_json TEXT, candidates_json TEXT, rejected_json TEXT,
        usage_json TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS assets (
        id TEXT PRIMARY KEY, kind TEXT, filename TEXT, path TEXT, license_note TEXT,
        created_at REAL, deleted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_json TEXT);
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_clips_project ON clips(project_id);
    """,
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init() -> None:
    config.ensure_dirs()
    with tx() as c:
        c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        current = int(row["value"]) if row else 0
        for version in range(current + 1, len(MIGRATIONS) + 1):
            c.executescript(MIGRATIONS[version - 1])
            c.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(version),),
            )


def schema_version() -> int:
    with tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in list(d.keys()):
        if k.endswith("_json"):
            raw = d.pop(k)
            d[k[:-5]] = json.loads(raw) if raw else None
    return d


def fetchone(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with tx() as c:
        return row_to_dict(c.execute(sql, params).fetchone())


def fetchall(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with tx() as c:
        return [row_to_dict(r) for r in c.execute(sql, params).fetchall()]  # type: ignore[misc]


def execute(sql: str, params: tuple = ()) -> None:
    with tx() as c:
        c.execute(sql, params)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def get_setting(key: str, default: Any = None) -> Any:
    row = fetchone("SELECT value_json FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: Any) -> None:
    execute(
        "INSERT INTO settings(key, value_json) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
        (key, dumps(value)),
    )
