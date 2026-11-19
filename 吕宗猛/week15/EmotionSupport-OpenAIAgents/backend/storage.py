"""本地 SQLite 会话与模型配置存储。

表结构：
- sessions: 一次对话
- messages: 对话中的消息，meta_json 保存情感识别结果与回应 Agent 信息
- model_config: 单行模型配置，未配置时不存在记录
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import config

DB_PATH = Path(config.SESSION_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session_id
                ON messages(session_id, id);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions(updated_at DESC);
            CREATE TABLE IF NOT EXISTS model_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL DEFAULT '',
                model_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def _row_message(row: sqlite3.Row) -> dict[str, Any]:
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except json.JSONDecodeError:
        meta = {}
    return {
        "id": int(row["id"]),
        "session_id": str(row["session_id"]),
        "role": str(row["role"]),
        "content": str(row["content"]),
        "meta": meta if isinstance(meta, dict) else {},
        "created_at": str(row["created_at"]),
    }


def _row_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": str(row["title"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "message_count": int(row["message_count"]) if "message_count" in row.keys() else 0,
    }


def create_session(title: str) -> dict[str, Any]:
    session_id = uuid.uuid4().hex
    now = _now()
    with _db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title.strip() or "新的对话", now, now),
        )
        row = conn.execute(
            "SELECT s.*, 0 AS message_count FROM sessions s WHERE s.id = ?",
            (session_id,),
        ).fetchone()
    return _row_session(row)


def get_session(session_id: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
            FROM sessions s
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
    return _row_session(row) if row else None


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
            FROM sessions s
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_session(row) for row in rows]


def add_message(
    session_id: str,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if role not in {"user", "assistant"}:
        raise ValueError("role 必须是 user 或 assistant")
    now = _now()
    with _db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (session_id, role, content, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, json.dumps(meta or {}, ensure_ascii=False), now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _row_message(row)


def get_recent_messages(session_id: str, rounds: int) -> list[dict[str, Any]]:
    """取最近 rounds 轮（最多 rounds*2 条），按时间正序返回。"""
    limit = max(1, int(rounds)) * 2
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    messages = [_row_message(row) for row in rows]
    messages.reverse()
    if messages and messages[0]["role"] == "assistant":
        messages = messages[1:]
    return messages


def get_message_page(
    session_id: str,
    limit: int = 5,
    before_id: int | None = None,
) -> dict[str, Any]:
    """从新到旧取一页消息，返回时按时间正序排列。"""
    limit = max(1, min(int(limit), 20))
    params: list[Any] = [session_id]
    sql = "SELECT * FROM messages WHERE session_id = ?"
    if before_id is not None:
        sql += " AND id < ?"
        params.append(int(before_id))
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit + 1)

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = [_row_message(row) for row in rows]
    messages.reverse()
    return {
        "messages": messages,
        "has_more": has_more,
        "next_before_id": messages[0]["id"] if messages else None,
    }


def get_model_config() -> dict[str, Any] | None:
    """返回模型配置；没有记录时返回 None。"""
    with _db() as conn:
        row = conn.execute("SELECT * FROM model_config WHERE id = 1").fetchone()
    if not row:
        return None
    return {
        "base_url": str(row["base_url"]),
        "api_key": str(row["api_key"]),
        "model_name": str(row["model_name"]),
        "updated_at": str(row["updated_at"]),
    }


def save_model_config(base_url: str, api_key: str, model_name: str) -> dict[str, Any]:
    now = _now()
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO model_config (id, base_url, api_key, model_name, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                base_url = excluded.base_url,
                api_key = excluded.api_key,
                model_name = excluded.model_name,
                updated_at = excluded.updated_at
            """,
            (base_url, api_key, model_name, now),
        )
        row = conn.execute("SELECT * FROM model_config WHERE id = 1").fetchone()
    return {
        "base_url": str(row["base_url"]),
        "api_key": str(row["api_key"]),
        "model_name": str(row["model_name"]),
        "updated_at": str(row["updated_at"]),
    }
