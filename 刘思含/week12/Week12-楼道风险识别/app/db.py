"""SQLite 历史记录。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/history.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    request_id TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    risk_level TEXT,
    risk_score INTEGER,
    is_hallway INTEGER,
    image_url TEXT,
    latency_ms INTEGER,
    reason TEXT
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def save_record(
    *,
    request_id: str,
    provider: str,
    model: str,
    risk_level: str | None,
    risk_score: int | None,
    is_hallway: bool | None,
    image_url: str | None,
    latency_ms: int,
    reason: str | None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO analysis (created_at, request_id, provider, model, risk_level,"
            " risk_score, is_hallway, image_url, latency_ms, reason)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                request_id,
                provider,
                model,
                risk_level,
                risk_score,
                None if is_hallway is None else int(is_hallway),
                image_url,
                latency_ms,
                reason,
            ),
        )


def list_records(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM analysis ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT risk_level, COUNT(*) AS n FROM analysis GROUP BY risk_level"
        ).fetchall()
    return {r["risk_level"] or "unknown": r["n"] for r in rows}
