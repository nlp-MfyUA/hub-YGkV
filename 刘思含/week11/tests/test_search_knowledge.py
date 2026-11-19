"""Tests for the read-only knowledge-base lookup tool."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.tools.search_knowledge import (
    reset_kb_cache,
    search_knowledge,
    search_knowledge_payload,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app" / "db" / "schema.sql"

QUERY_LOG: list[str] = []

KB_ENTRIES = [
    (
        1,
        "高危漏洞有多少",
        "SELECT COUNT(*) FROM v_vulnerability WHERE severity='高危'",
        None,
        "approved",
    ),
    (
        2,
        "按漏洞类型分布",
        "SELECT type_name, COUNT(*) FROM v_vulnerability GROUP BY type_name",
        None,
        "approved",
    ),
    (
        3,
        "哪份报告漏洞最多",
        (
            "SELECT source_file, COUNT(*) FROM v_vulnerability "
            "GROUP BY source_file ORDER BY 2 DESC LIMIT 1"
        ),
        None,
        "approved",
    ),
    # 原为 "高危漏洞"，与第 1 条构成前缀关系，用户问"高危漏洞"时第 4 条完全匹配、
    # 第 1 条部分匹配，无法测试"并列取最长"。改为 "漏洞高危" 使两者部分重叠。
    (4, "漏洞高危", "SELECT 1", None, "approved"),
    (5, "已修复的高危漏洞", "SELECT 2", None, "approved"),
    (6, "今天天气如何", "SELECT 3", None, "pending"),
    (7, "被拒绝的模板", "SELECT 4", None, "rejected"),
]


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create an isolated database with kb_entry fixtures."""
    path = tmp_path_factory.mktemp("search_knowledge") / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        """
        INSERT INTO kb_entry (
            id, question_pattern, sql_template, params_schema, status,
            hit_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 0, '2026-01-01', '2026-01-01')
        """,
        KB_ENTRIES,
    )
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


@pytest.fixture
def sql_env(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> Path:
    """Point search_knowledge at the test database and clear the cache."""
    monkeypatch.setenv("VULN_DB_PATH", str(db_path))
    reset_kb_cache()
    yield db_path
    reset_kb_cache()


def test_exact_match(sql_env: Path) -> None:
    payload = json.loads(search_knowledge_payload("高危漏洞有多少"))
    assert payload["hit"] is True
    assert payload["kb_entry_id"] == 1
    assert "COUNT(*)" in payload["sql_template"]


def test_partial_match(sql_env: Path) -> None:
    payload = json.loads(search_knowledge_payload("高危漏洞数量"))
    assert payload["hit"] is True
    assert payload["kb_entry_id"] == 1


def test_no_match(sql_env: Path) -> None:
    payload = json.loads(search_knowledge_payload("今天天气如何呀"))
    assert payload == {"hit": False}


def test_pending_and_rejected_not_returned(sql_env: Path) -> None:
    pending = json.loads(search_knowledge_payload("今天天气如何"))
    assert pending == {"hit": False}
    rejected = json.loads(search_knowledge_payload("被拒绝的模板"))
    assert rejected == {"hit": False}


def test_tie_breaks_on_longest_pattern(sql_env: Path) -> None:
    """验证计数型问题下完整匹配优先，且并列时取更长的 pattern。

    原 fixture 第 4 条为 "高危漏洞"，是第 1 条的严格前缀：问 "高危漏洞" 时
    第 4 条覆盖率 1.0、第 1 条 < 1.0，不构成并列，测不到"取最长"。改为
    "漏洞高危" 后两者对计数型问题并列（同为 1.0），才由 pattern 长度决胜。
    """
    payload = json.loads(search_knowledge_payload("高危漏洞有多少个"))
    assert payload["hit"] is True
    assert payload["kb_entry_id"] == 1


def test_queries_are_readonly(sql_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    statements: list[str] = []
    real_connect = sqlite3.connect

    def wrapper(database: str, *args, **kwargs):
        conn = real_connect(database, *args, **kwargs)
        set_trace_callback = getattr(conn, "set_trace_callback", None)
        if set_trace_callback is not None:
            set_trace_callback(QUERY_LOG.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", wrapper)
    reset_kb_cache()
    search_knowledge_payload("高危漏洞有多少")
    statements.extend(QUERY_LOG)
    assert statements
    for sql in statements:
        upper = sql.upper()
        assert "UPDATE" not in upper
        assert "INSERT" not in upper
        assert "DELETE" not in upper
        assert "HIT_COUNT" not in upper


def test_cache_avoids_second_query(
    sql_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = search_knowledge_payload("高危漏洞有多少")
    calls: list[str] = []
    real_connect = sqlite3.connect

    def wrapper(database: str, *args, **kwargs):
        calls.append(database)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", wrapper)
    second = search_knowledge_payload("高危漏洞有多少")
    assert second == first
    assert calls == []


def test_function_tool_wrapper() -> None:
    from agents import FunctionTool

    assert isinstance(search_knowledge, FunctionTool)
    assert search_knowledge.name == "search_knowledge"
