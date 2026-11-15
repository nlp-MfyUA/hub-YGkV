"""Tests for the read-only execute_sql tool."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.tools.execute_sql import (
    ForbiddenSQLError,
    execute_sql,
    execute_sql_query,
    validate_readonly_sql,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app" / "db" / "schema.sql"

MALICIOUS_SQL = [
    "DELETE FROM v_vulnerability",
    "UPDATE v_report SET status='orphaned'",
    "INSERT INTO kb_entry VALUES (1, 'x', 'y')",
    "DROP TABLE v_vulnerability",
    "ALTER TABLE v_vulnerability ADD COLUMN x TEXT",
    "CREATE TABLE evil (id INTEGER)",
    "ATTACH DATABASE '/tmp/evil.db' AS evil",
    "DETACH DATABASE evil",
    "PRAGMA table_info(v_vulnerability)",
    "VACUUM",
    "SELECT 1; DROP TABLE v_vulnerability",
    "SELECT * FROM v_vulnerability; DELETE FROM v_report",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM pdf_index",
    "SELECT * FROM v_image_evidence_fts",
    "SELECT name FROM sqlite_schema",
    "SELECT * FROM v_vulnerability WHERE id IN (SELECT id FROM pdf_index)",
    "/* comment */ DELETE FROM v_vulnerability",
    "-- comment\nDROP TABLE v_report",
    "DeLeTe FrOm v_vulnerability",
    "WITH x AS (DELETE FROM v_vulnerability RETURNING *) SELECT * FROM x",
    # CTE 中查非法表
    "WITH t AS (SELECT * FROM pdf_index) SELECT * FROM t",
    "WITH t AS (SELECT * FROM v_image_evidence_fts) SELECT COUNT(*) FROM t",
]

VALID_SQL = [
    "SELECT COUNT(*) FROM v_vulnerability",
    "SELECT severity, COUNT(*) FROM v_vulnerability GROUP BY severity",
    "SELECT * FROM v_report WHERE report_type='pentest'",
    "SELECT * FROM v_type_catalog",
    "SELECT * FROM kb_entry WHERE status='approved'",
    "SELECT * FROM v_image_evidence WHERE source_file='x.pdf'",
    "SELECT * FROM v_retest_result WHERE retest_status='fixed'",
    "WITH t AS (SELECT * FROM v_vulnerability) SELECT COUNT(*) FROM t",
    (
        "SELECT v.vuln_name, r.retest_status FROM v_vulnerability v "
        "JOIN v_retest_result r ON v.id = r.vuln_id"
    ),
]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create an isolated read-only test database."""
    path = tmp_path_factory.mktemp("execute_sql") / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO v_report
            (id, report_name, report_type, status, created_at, updated_at)
        VALUES (1, 'bulk.pdf', 'pentest', 'active', '2026-01-01', '2026-01-01')
        """
    )
    conn.executemany(
        """
        INSERT INTO v_vulnerability (
            report_id, source_file, vuln_name, severity, severity_raw,
            type_code, type_name, component, instance_index,
            extraction_method, confidence, status, created_at, updated_at
        ) VALUES (1, 'bulk.pdf', ?, '高危', 'High', 'SQLI', 'SQL 注入',
                  '', 1, 'text_block', 'high', 'active',
                  '2026-01-01', '2026-01-01')
        """,
        [(f"vulnerability-{index}",) for index in range(1500)],
    )
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


@pytest.fixture
def sql_env(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> Path:
    """Point execute_sql at the isolated test database."""
    monkeypatch.setenv("VULN_DB_PATH", str(db_path))
    return db_path


@pytest.mark.parametrize("sql", MALICIOUS_SQL)
def test_malicious_sql_is_rejected(sql: str) -> None:
    with pytest.raises(ForbiddenSQLError):
        validate_readonly_sql(sql)


@pytest.mark.parametrize("sql", VALID_SQL)
def test_valid_sql_passes_and_executes(sql: str, sql_env: Path) -> None:
    assert validate_readonly_sql(sql) is True
    payload = json.loads(execute_sql_query(sql))
    assert payload["ok"] is True
    assert payload["sql"] == sql
    assert "columns" in payload
    assert "rows" in payload
    assert "row_count" in payload


def test_result_limit_and_truncated_flag(sql_env: Path) -> None:
    payload = json.loads(execute_sql_query("SELECT * FROM v_vulnerability"))
    assert payload["ok"] is True
    assert payload["row_count"] == 1000
    assert len(payload["rows"]) == 1000
    assert payload.get("truncated") is True


def test_connection_uses_readonly_uri(
    sql_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[tuple[str, dict]] = []
    real_connect = sqlite3.connect

    def wrapper(database: str, *args, **kwargs):
        captured.append((database, kwargs))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", wrapper)
    payload = json.loads(execute_sql_query("SELECT 1"))
    assert payload["ok"] is True
    assert captured
    uri, kwargs = captured[0]
    assert "mode=ro" in uri
    assert kwargs.get("uri") is True
    assert kwargs.get("timeout") == 5.0


def test_invalid_sql_returns_error_without_raising(sql_env: Path) -> None:
    sql = "SELECT * FROM pdf_index"
    payload = json.loads(execute_sql_query(sql))
    assert payload["ok"] is False
    assert payload["sql"] == sql
    assert "table not allowed" in payload["error"]


def test_tool_name() -> None:
    assert execute_sql.name == "execute_sql"


@pytest.mark.parametrize(
    ("sql", "bad_table"),
    [
        ("WITH t AS (SELECT * FROM pdf_index) SELECT * FROM t", "pdf_index"),
        (
            "WITH t AS (SELECT * FROM v_image_evidence_fts) " "SELECT COUNT(*) FROM t",
            "v_image_evidence_fts",
        ),
    ],
)
def test_cte_illegal_table_reports_real_table(sql: str, bad_table: str) -> None:
    with pytest.raises(ForbiddenSQLError) as error:
        validate_readonly_sql(sql)
    message = str(error.value)
    assert message == f"table not allowed: {bad_table}"


def test_function_tool_schema() -> None:
    """验证 @function_tool 装饰后的 schema 正确，LLM 能正确传参。"""
    from agents import FunctionTool

    assert isinstance(execute_sql, FunctionTool)
    schema = execute_sql.params_json_schema
    assert "sql" in schema["properties"]
    assert schema["properties"]["sql"]["type"] == "string"
    assert schema["required"] == ["sql"]
