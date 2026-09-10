"""SQLite 数据层：连接管理、建表、通用 CRUD。"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    topic TEXT NOT NULL,
    model_id INTEGER REFERENCES models(id),
    max_rounds INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / running / done / error
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER UNIQUE NOT NULL REFERENCES tasks(id),
    report_md TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model_name TEXT NOT NULL,
    api_key_enc TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    health_status TEXT NOT NULL DEFAULT 'unknown',  -- ok / fail / unknown
    health_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def query(sql, args=()):
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def query_one(sql, args=()):
    with get_conn() as conn:
        row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def execute(sql, args=()):
    with get_conn() as conn:
        cur = conn.execute(sql, args)
        return cur.lastrowid
