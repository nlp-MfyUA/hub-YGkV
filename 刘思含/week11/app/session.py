"""Per-user chat session storage.

The Agents SDK in this environment does not ship ``SQLiteSession``, so this
module provides an equivalent session backed by a small SQLite table. It is
only used by ``app/main.py`` to keep short multi-turn context for the CLI.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ChatSession:
    """Minimal conversation history for one user."""

    session_id: str
    db_path: Path = Path("data") / "chat_history.db"
    max_turns: int = 10

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_session (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def add_turn(self, question: str, answer: str) -> None:
        """Append one user/assistant turn."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executemany(
                """
                INSERT INTO chat_session
                    (session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (self.session_id, "user", question, now),
                    (self.session_id, "assistant", answer, now),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def recent_turns(self) -> list[tuple[str, str]]:
        """Return the most recent (role, content) pairs."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT role, content FROM chat_session
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (self.session_id, self.max_turns * 2),
            ).fetchall()
        finally:
            conn.close()
        return list(reversed(rows))

    def history_text(self) -> str:
        """Render history as plain text for the prompt."""
        return "\n".join(f"{role}: {content}" for role, content in self.recent_turns())


def get_session(user_id: str, db_dir: Path = Path("data")) -> ChatSession:
    """Return the per-user session persisted under *db_dir*."""
    return ChatSession(
        session_id=user_id,
        db_path=Path(db_dir) / f"chat_history_{user_id}.db",
    )
