"""Tests for the FTS5-backed image evidence search tool."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.tools.search_image_evidence import (
    build_fts_query,
    escape_like_literal,
    search_image_evidence,
    search_image_evidence_payload,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app" / "db" / "schema.sql"


def _insert_image(
    conn: sqlite3.Connection,
    index: int,
    ocr_text: str,
    linked: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO v_image_evidence (
            report_id, source_file, source_page, image_index, image_path,
            image_type, ocr_text, ocr_confidence, linked_vuln_name,
            status, created_at, updated_at
        ) VALUES (1, 'img.pdf', ?, ?, ?, 'screenshot', ?, 'high', ?,
                  'active', '2026-01-01', '2026-01-01')
        """,
        (index, index, f"img/{index}_0.png", ocr_text, linked),
    )


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create an isolated database with image evidence fixtures."""
    path = tmp_path_factory.mktemp("search_image") / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO v_report
            (id, report_name, report_type, status, created_at, updated_at)
        VALUES (1, 'img.pdf', 'pentest', 'active', '2026-01-01', '2026-01-01')
        """
    )
    _insert_image(conn, 1, "GET /api?id=1' OR 1=1-- HTTP/1.1", "SQL 注入")
    _insert_image(conn, 2, "error in SQL syntax near OR 1=1", "SQL 注入")
    _insert_image(conn, 3, "logic bypass evidence", None)
    _insert_image(conn, 4, "unrelated chart with OR value", "XSS")
    _insert_image(conn, 5, "totally different text", "CSRF")
    _insert_image(conn, 6, "账号密码登录失败，请重试", "账号密码泄露")
    _insert_image(conn, 7, "任意文件上传 HTTP/1.1 400 Bad Request", "任意文件上传")
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


@pytest.fixture(scope="module")
def limit_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Database with eight matches and one long OCR record."""
    path = tmp_path_factory.mktemp("search_image_limit") / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO v_report
            (id, report_name, report_type, status, created_at, updated_at)
        VALUES (1, 'img.pdf', 'pentest', 'active', '2026-01-01', '2026-01-01')
        """
    )
    for index in range(1, 9):
        _insert_image(conn, index, f"payload marker {index}", "限额漏洞")
    _insert_image(conn, 9, "x" * 1500, "长文本漏洞")
    for index in (10, 11, 12):
        _insert_image(conn, index, f"payload marker target {index}", "目标漏洞")
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


@pytest.fixture
def sql_env(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> Path:
    monkeypatch.setenv("VULN_DB_PATH", str(db_path))
    return db_path


def test_vuln_name_and_keywords(sql_env: Path) -> None:
    payload = json.loads(search_image_evidence_payload("SQL 注入", ["OR 1=1"]))
    assert payload["hit"] is True
    assert payload["count"] == 2
    assert all("1=1" in item["ocr_text"] for item in payload["items"])
    assert all(item["linked_vuln_name"] == "SQL 注入" for item in payload["items"])


def test_keywords_only(sql_env: Path) -> None:
    payload = json.loads(search_image_evidence_payload(None, ["totally"]))
    assert payload["hit"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["linked_vuln_name"] == "CSRF"


def test_two_char_keyword_uses_like(sql_env: Path) -> None:
    payload = json.loads(
        search_image_evidence_payload("账号密码泄露", ["账号"])
    )
    assert payload["hit"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["linked_vuln_name"] == "账号密码泄露"
    assert payload["total_matched"] == 1
    assert payload["truncated"] is False
    assert payload["query_used"] == "LIKE:账号"


def test_mixed_keywords_merge_fts_and_like(sql_env: Path) -> None:
    payload = json.loads(
        search_image_evidence_payload(None, ["账号", "totally"])
    )
    assert payload["hit"] is True
    assert payload["count"] == 2
    names = {item["linked_vuln_name"] for item in payload["items"]}
    assert names == {"账号密码泄露", "CSRF"}


def test_vuln_filter_applies_before_limit(
    monkeypatch: pytest.MonkeyPatch, limit_db: Path
) -> None:
    monkeypatch.setenv("VULN_DB_PATH", str(limit_db))
    payload = json.loads(
        search_image_evidence_payload("目标漏洞", ["marker"], limit=5)
    )
    assert payload["hit"] is True
    assert payload["count"] == 3
    assert all(
        item["linked_vuln_name"] == "目标漏洞" for item in payload["items"]
    )


def test_empty_result(sql_env: Path) -> None:
    payload = json.loads(search_image_evidence_payload(None, ["不存在的词"]))
    assert payload["hit"] is False
    assert payload["count"] == 0


def test_fts_special_characters(sql_env: Path) -> None:
    payload = json.loads(search_image_evidence_payload(None, ["OR 1=1", 'GET" /api']))
    assert "error" not in payload
    assert payload["query_used"].startswith('"OR 1=1"')


def test_limit(monkeypatch: pytest.MonkeyPatch, limit_db: Path) -> None:
    monkeypatch.setenv("VULN_DB_PATH", str(limit_db))
    payload = json.loads(
        search_image_evidence_payload("限额漏洞", ["marker"], limit=3)
    )
    assert payload["hit"] is True
    assert payload["count"] == 3
    assert payload["total_matched"] == 8
    assert payload["truncated"] is True
    assert payload["hint"] == "还有更多图片证据未返回，可调大 limit 再查"


def test_default_limit_is_ten(
    monkeypatch: pytest.MonkeyPatch, limit_db: Path
) -> None:
    monkeypatch.setenv("VULN_DB_PATH", str(limit_db))
    payload = json.loads(
        search_image_evidence_payload("限额漏洞", ["marker"])
    )
    assert payload["hit"] is True
    assert payload["count"] == 8
    assert payload["total_matched"] == 8
    assert payload["truncated"] is False
    assert "hint" not in payload


def test_ocr_truncation(monkeypatch: pytest.MonkeyPatch, limit_db: Path) -> None:
    monkeypatch.setenv("VULN_DB_PATH", str(limit_db))
    payload = json.loads(search_image_evidence_payload("长文本漏洞", ["xxx"], limit=5))
    assert payload["hit"] is True
    item = payload["items"][0]
    assert len(item["ocr_text"]) == 1000
    assert item["ocr_text_truncated"] is True


def test_vuln_name_percent_is_escaped(sql_env: Path) -> None:
    # '%' must be escaped: unescaped "SQL%注入" would match "SQL 注入"
    # in the first pass, then the fallback would return rows and hide the bug.
    escaped = json.loads(search_image_evidence_payload("SQL%注入", ["OR 1=1"]))
    assert escaped["hit"] is False
    literal = json.loads(search_image_evidence_payload("SQL 注入", ["OR 1=1"]))
    assert literal["hit"] is True
    assert escape_like_literal("SQL%注入") == "%SQL\%注入%"


def test_fts_query_escaping() -> None:
    assert build_fts_query(['a"b', "OR 1=1"]) == '"a""b" OR "OR 1=1"'


def test_function_tool_wrapper() -> None:
    from agents import FunctionTool

    assert isinstance(search_image_evidence, FunctionTool)
    assert search_image_evidence.name == "search_image_evidence"
