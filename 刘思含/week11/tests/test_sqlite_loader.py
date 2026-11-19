"""Tests for the canonical vulnerability SQLite loader."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from pipeline.common.types import CanonicalVulnRecord
from pipeline.phase3_load.sqlite_loader import load_file_records

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app" / "db" / "schema.sql"
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "parsed_output_samples"
    / "simple_table_canonical.json"
)

SEVERITY_MAP = {
    "high": "高危",
    "medium": "中危",
    "low": "低危",
    "critical": "高危",
    "info": "信息",
}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _type_catalog(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    return {
        row[0]: (row[1], row[2] or "")
        for row in conn.execute(
            "SELECT type_code, type_name, category FROM v_type_catalog"
        )
    }


def _records() -> list[CanonicalVulnRecord]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [CanonicalVulnRecord(**item) for item in payload]


def _load(conn: sqlite3.Connection, records: list[CanonicalVulnRecord]):
    return load_file_records(
        conn,
        "simple_table.pdf",
        "pentest",
        records,
        SEVERITY_MAP,
        _type_catalog(conn),
    )


def test_first_write_inserts_three() -> None:
    conn = _conn()
    result = _load(conn, _records())
    assert result.status == "pass"
    assert result.inserted == 3
    assert result.updated == 0
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM v_vulnerability").fetchone()[0] == 3
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM v_vulnerability WHERE status='active'"
        ).fetchone()[0]
        == 3
    )


def test_duplicate_write_updates_not_inserts() -> None:
    conn = _conn()
    records = _records()
    _load(conn, records)
    result = _load(conn, records)
    assert result.inserted == 0
    assert result.updated == 3
    assert conn.execute("SELECT COUNT(*) FROM v_vulnerability").fetchone()[0] == 3


def test_update_existing_severity_and_timestamp() -> None:
    conn = _conn()
    records = _records()
    _load(conn, records)
    before = {
        row[0]: row[1]
        for row in conn.execute("SELECT vuln_name, updated_at FROM v_vulnerability")
    }
    time.sleep(0.002)
    records[0] = CanonicalVulnRecord(
        **{**records[0].to_dict(), "severity_raw": "Medium"}
    )
    result = _load(conn, records)
    assert result.updated == 3
    severity = conn.execute(
        "SELECT severity FROM v_vulnerability WHERE vuln_name='SQL Injection'"
    ).fetchone()[0]
    assert severity == "中危"
    after = {
        row[0]: row[1]
        for row in conn.execute("SELECT vuln_name, updated_at FROM v_vulnerability")
    }
    assert after["SQL Injection"] != before["SQL Injection"]
    assert after["XSS"] == before["XSS"]
    assert after["Info Disclosure"] == before["Info Disclosure"]


def test_difference_soft_delete_and_reactivate() -> None:
    conn = _conn()
    full = _records()
    _load(conn, full)
    subset = full[:2]
    result = _load(conn, subset)
    assert result.superseded == 1
    status = conn.execute(
        "SELECT status FROM v_vulnerability WHERE vuln_name='Info Disclosure'"
    ).fetchone()[0]
    assert status == "superseded"
    assert conn.execute("SELECT COUNT(*) FROM v_vulnerability").fetchone()[0] == 3
    result = _load(conn, full)
    assert result.superseded == 0
    status = conn.execute(
        "SELECT status FROM v_vulnerability WHERE vuln_name='Info Disclosure'"
    ).fetchone()[0]
    assert status == "active"


def test_empty_records_writes_report_and_skips_vulns() -> None:
    conn = _conn()
    result = load_file_records(
        conn,
        "no_vuln.pdf",
        "pentest",
        [],
        SEVERITY_MAP,
        _type_catalog(conn),
    )
    assert result.status == "skipped_no_vulns"
    assert result.inserted == 0
    assert result.updated == 0
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM v_vulnerability").fetchone()[0] == 0


def test_transaction_rolls_back_on_invalid_record() -> None:
    conn = _conn()
    valid = _records()[0]
    invalid = CanonicalVulnRecord(
        **{
            **valid.to_dict(),
            "description_snippet": "a" * 304,
        }
    )
    result = load_file_records(
        conn,
        "rollback.pdf",
        "pentest",
        [valid, invalid],
        SEVERITY_MAP,
        _type_catalog(conn),
    )
    assert result.status == "fail"
    assert result.error
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v_vulnerability").fetchone()[0] == 0


def test_empty_vuln_name_raises_and_rolls_back() -> None:
    conn = _conn()
    valid = _records()[0]
    invalid = CanonicalVulnRecord(**{**valid.to_dict(), "vuln_name": ""})
    with pytest.raises(ValueError, match="empty vuln_name"):
        load_file_records(
            conn,
            "empty_name.pdf",
            "pentest",
            [valid, invalid],
            SEVERITY_MAP,
            _type_catalog(conn),
        )
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v_vulnerability").fetchone()[0] == 0


def test_duplicate_names_do_not_collapse() -> None:
    conn = _conn()
    fixture = (
        ROOT
        / "tests"
        / "fixtures"
        / "parsed_output_samples"
        / "duplicate_names_canonical.json"
    )
    records = [
        CanonicalVulnRecord(**item)
        for item in json.loads(fixture.read_text(encoding="utf-8"))
    ]
    result = load_file_records(
        conn,
        "duplicate_names.pdf",
        "pentest",
        records,
        SEVERITY_MAP,
        _type_catalog(conn),
    )
    assert result.inserted == 3
    assert result.updated == 0
    rows = conn.execute(
        "SELECT instance_index FROM v_vulnerability ORDER BY instance_index"
    ).fetchall()
    assert [row[0] for row in rows] == [1, 2, 3]
