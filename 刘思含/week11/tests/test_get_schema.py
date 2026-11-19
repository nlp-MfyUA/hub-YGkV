"""Tests for the schema introspection tool."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.tools.get_schema import get_schema, get_schema_payload, reset_schema_cache

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app" / "db" / "schema.sql"
TABLES = (
    "v_report",
    "v_vulnerability",
    "v_type_catalog",
    "kb_entry",
    "v_image_evidence",
    "v_retest_result",
)


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create an isolated database with the project schema."""
    path = tmp_path_factory.mktemp("get_schema") / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


@pytest.fixture
def sql_env(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> Path:
    """Point get_schema at the test database and clear the cache."""
    monkeypatch.setenv("VULN_DB_PATH", str(db_path))
    reset_schema_cache()
    yield db_path
    reset_schema_cache()


def test_first_call_returns_six_tables(sql_env: Path) -> None:
    payload = json.loads(get_schema_payload())
    assert set(payload["tables"]) == set(TABLES)
    conn = sqlite3.connect(sql_env)
    try:
        for table in TABLES:
            actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            reported = [
                column["name"] for column in payload["tables"][table]["columns"]
            ]
            assert reported == actual, table
    finally:
        conn.close()


def test_severity_enum(sql_env: Path) -> None:
    payload = json.loads(get_schema_payload())
    columns = {
        column["name"]: column
        for column in payload["tables"]["v_vulnerability"]["columns"]
    }
    assert columns["severity"]["enum"] == ["高危", "中危", "低危", "信息"]


def test_type_catalog_has_expanded_rows(sql_env: Path) -> None:
    payload = json.loads(get_schema_payload())
    assert len(payload["type_catalog"]) == 19
    codes = {row["type_code"] for row in payload["type_catalog"]}
    assert {
        "SQLI",
        "XSS",
        "UNKNOWN",
        "AUTHZ",
        "LOGIC",
        "UPLOAD",
        "LEAK",
        "CSP",
        "CAPTCHA",
        "DOMXSS",
    } <= codes


def test_second_call_does_not_query_database(
    sql_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = get_schema_payload()
    calls: list[str] = []
    real_connect = sqlite3.connect

    def wrapper(database: str, *args, **kwargs):
        calls.append(database)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", wrapper)
    second = get_schema_payload()
    assert second == first
    assert calls == []


def test_connection_is_readonly(sql_env: Path) -> None:
    calls: list[tuple[str, dict]] = []
    real_connect = sqlite3.connect

    def wrapper(database: str, *args, **kwargs):
        calls.append((database, kwargs))
        return real_connect(database, *args, **kwargs)

    import app.tools.get_schema as module

    original = module.sqlite3.connect
    module.sqlite3.connect = wrapper
    try:
        reset_schema_cache()
        get_schema_payload()
    finally:
        module.sqlite3.connect = original
    assert calls
    uri, kwargs = calls[0]
    assert "mode=ro" in uri
    assert kwargs.get("uri") is True


def test_function_tool_wrapper() -> None:
    from agents import FunctionTool

    assert isinstance(get_schema, FunctionTool)
    assert get_schema.name == "get_schema"
