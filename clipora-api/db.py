"""SQLite 저장소. 단일 파일 DB라 Render/Fly 같은 곳에서는 영구 디스크에 두세요 (DATABASE_PATH)."""

import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "clipora.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    plan_expires_at INTEGER,
    balance_sec REAL NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    payment_key TEXT,
    created_at INTEGER NOT NULL,
    paid_at INTEGER
);
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    created_at INTEGER NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    with tx() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def tx():
    """직렬화된 트랜잭션. 사용량 차감처럼 읽고-쓰는 작업이 겹치지 않게 합니다."""
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
