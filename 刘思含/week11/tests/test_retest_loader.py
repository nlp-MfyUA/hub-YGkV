"""Tests for the retest result loader."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pipeline.common.types import CanonicalVulnRecord, RetestRecord
from pipeline.phase3_load.retest_loader import load_retest_records
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

PARENT_SPECS = (
    ("SQL Injection", "/api/login"),
    ("XSS", "/search"),
    ("Info Disclosure", "/debug"),
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _catalog(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    return {
        row[0]: (row[1], row[2] or "")
        for row in conn.execute(
            "SELECT type_code, type_name, category FROM v_type_catalog"
        )
    }


def _parent_records() -> list[CanonicalVulnRecord]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [CanonicalVulnRecord(**item) for item in payload]


def _setup_parent(conn: sqlite3.Connection) -> int:
    result = load_file_records(
        conn,
        "simple_table.pdf",
        "pentest",
        _parent_records(),
        SEVERITY_MAP,
        _catalog(conn),
    )
    assert result.report_id is not None
    return result.report_id


def _retest_records() -> list[RetestRecord]:
    return [
        RetestRecord(
            retest_report_path="retest.pdf",
            raw_vuln_name=name,
            component=component,
            retest_status_raw="该漏洞已修复完成。",
            retest_status="fixed",
            retest_date="2026年2月-6月",
            evidence_snippet="该漏洞已修复完成。",
            source_page=5,
            evidence_page=12,
            parent_vuln_name=name,
        )
        for name, component in PARENT_SPECS
    ]


def test_all_records_match_exactly() -> None:
    conn = _conn()
    parent_id = _setup_parent(conn)
    result = load_retest_records(conn, "retest.pdf", _retest_records(), parent_id)
    assert result.status == "pass"
    assert result.matched == 3
    assert result.unmatched == 0
    assert result.inserted == 3
    rows = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchall()
    assert len(rows) == 3
    assert all(row[0] is not None and row[1] == "exact" for row in rows)


def test_partial_match() -> None:
    conn = _conn()
    parent_id = _setup_parent(conn)
    records = _retest_records()
    records[2] = RetestRecord(
        retest_report_path="retest.pdf",
        raw_vuln_name="Not In Parent",
        component="",
        retest_status_raw="该漏洞已修复完成。",
        retest_status="fixed",
        retest_date="2026年2月-6月",
        evidence_snippet="该漏洞已修复完成。",
        source_page=5,
        evidence_page=12,
        parent_vuln_name="Not In Parent",
    )
    result = load_retest_records(conn, "retest.pdf", records, parent_id)
    assert result.matched == 2
    assert result.unmatched == 1
    row = conn.execute(
        """
        SELECT vuln_id, match_confidence
        FROM v_retest_result WHERE raw_vuln_name='Not In Parent'
        """
    ).fetchone()
    assert row[0] is None
    assert row[1] == "none"


def test_parent_none_leaves_all_unmatched() -> None:
    conn = _conn()
    _setup_parent(conn)
    result = load_retest_records(conn, "retest.pdf", _retest_records(), None)
    assert result.matched == 0
    assert result.unmatched == 3
    rows = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchall()
    assert len(rows) == 3
    assert all(row[0] is None and row[1] == "none" for row in rows)


def test_duplicate_write_does_not_duplicate() -> None:
    conn = _conn()
    parent_id = _setup_parent(conn)
    records = _retest_records()
    load_retest_records(conn, "retest.pdf", records, parent_id)
    result = load_retest_records(conn, "retest.pdf", records, parent_id)
    assert result.inserted == 0
    assert result.updated == 3
    count = conn.execute("SELECT COUNT(*) FROM v_retest_result").fetchone()[0]
    assert count == 3


def test_difference_soft_delete() -> None:
    conn = _conn()
    parent_id = _setup_parent(conn)
    records = _retest_records()
    load_retest_records(conn, "retest.pdf", records, parent_id)
    result = load_retest_records(conn, "retest.pdf", records[:2], parent_id)
    assert result.superseded == 1
    status = conn.execute(
        """
        SELECT status FROM v_retest_result
        WHERE raw_vuln_name='Info Disclosure'
        """
    ).fetchone()[0]
    assert status == "superseded"
    count = conn.execute("SELECT COUNT(*) FROM v_retest_result").fetchone()[0]
    assert count == 3


def _duplicate_parent(conn: sqlite3.Connection, count: int) -> int:
    fixture = (
        ROOT
        / "tests"
        / "fixtures"
        / "parsed_output_samples"
        / "duplicate_names_canonical.json"
    )
    records = [
        CanonicalVulnRecord(**item)
        for item in json.loads(fixture.read_text(encoding="utf-8"))[:count]
    ]
    result = load_file_records(
        conn,
        "duplicate_names.pdf",
        "pentest",
        records,
        SEVERITY_MAP,
        _catalog(conn),
    )
    assert result.report_id is not None
    return result.report_id


def _duplicate_retests(count: int) -> list[RetestRecord]:
    return [
        RetestRecord(
            retest_report_path="retest_dup.pdf",
            raw_vuln_name="前端校验绕过",
            component=None,
            retest_status_raw="该漏洞已修复完成。",
            retest_status="fixed",
            retest_date="2026年2月-6月",
            evidence_snippet="该漏洞已修复完成。",
            source_page=5,
            instance_index=index,
            evidence_page=12,
            parent_vuln_name="前端校验绕过",
        )
        for index in range(1, count + 1)
    ]


def test_duplicate_names_match_by_instance_index() -> None:
    conn = _conn()
    parent_id = _duplicate_parent(conn, 3)
    result = load_retest_records(
        conn, "retest_dup.pdf", _duplicate_retests(3), parent_id
    )
    assert result.matched == 3
    assert result.unmatched == 0
    rows = conn.execute(
        """
        SELECT vuln_id, match_confidence
        FROM v_retest_result ORDER BY instance_index
        """
    ).fetchall()
    assert len(rows) == 3
    assert all(row[0] is not None and row[1] == "exact" for row in rows)
    assert len({row[0] for row in rows}) == 3


def test_instance_index_out_of_range_is_unmatched() -> None:
    conn = _conn()
    parent_id = _duplicate_parent(conn, 2)
    result = load_retest_records(
        conn, "retest_dup.pdf", _duplicate_retests(3), parent_id
    )
    assert result.matched == 2
    assert result.unmatched == 1
    row = conn.execute(
        """
        SELECT vuln_id, match_confidence FROM v_retest_result
        WHERE instance_index = 3
        """
    ).fetchone()
    assert row[0] is None
    assert row[1] == "none"


def _parent_with_names(conn: sqlite3.Connection, names: list[str]) -> int:
    """Insert a parent report whose vulnerabilities carry the given names."""
    records = [
        CanonicalVulnRecord(
            source_file="parent_names.pdf",
            vuln_name=name,
            severity_raw="高危",
            type_raw="越权访问",
            cvss_score=None,
            component=None,
            cwe_id=None,
            description_snippet="desc",
            source_page=3,
            instance_index=index,
            extraction_method="text_block",
            confidence="high",
        )
        for index, name in enumerate(names, 1)
    ]
    result = load_file_records(
        conn,
        "parent_names.pdf",
        "pentest",
        records,
        SEVERITY_MAP,
        _catalog(conn),
    )
    assert result.report_id is not None
    return result.report_id


def _single_retest(raw: str, parent_name: str, instance_index: int) -> RetestRecord:
    return RetestRecord(
        retest_report_path="retest_norm.pdf",
        raw_vuln_name=raw,
        component=None,
        retest_status_raw="该漏洞已修复完成。",
        retest_status="fixed",
        retest_date="2026年2月-6月",
        evidence_snippet="该漏洞已修复完成。",
        source_page=5,
        instance_index=instance_index,
        evidence_page=12,
        parent_vuln_name=parent_name,
    )


def test_ordinal_suffix_falls_back_to_fuzzy() -> None:
    """[FULL-002] parent '越权访问一' vs retest '越权访问' -> fuzzy."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["越权访问一"])
    result = load_retest_records(
        conn,
        "retest_norm.pdf",
        [_single_retest("越权访问", "越权访问", 1)],
        parent_id,
    )
    assert result.matched == 1
    assert result.unmatched == 0
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "fuzzy"


def test_status_suffix_falls_back_to_fuzzy() -> None:
    """[FULL-003] retest '弱口令（已修复）' vs parent '弱口令' -> fuzzy."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["弱口令"])
    result = load_retest_records(
        conn,
        "retest_norm.pdf",
        [_single_retest("弱口令（已修复）", "弱口令（已修复）", 1)],
        parent_id,
    )
    assert result.matched == 1
    assert result.unmatched == 0
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "fuzzy"


def test_normalized_ambiguous_without_instance_index_is_none() -> None:
    """Stripping must not fall back to 'take the first' when ambiguous."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["越权访问一", "越权访问二"])
    result = load_retest_records(
        conn,
        "retest_norm.pdf",
        [_single_retest("越权访问", "越权访问", 3)],
        parent_id,
    )
    assert result.matched == 0
    assert result.unmatched == 1
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is None
    assert row[1] == "none"



def test_two_digit_ordinal_falls_back_to_fuzzy() -> None:
    """[FULL-006] retest '纵向越权 01' vs parent '纵向越权' -> fuzzy."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["纵向越权"])
    load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("纵向越权 01", "纵向越权 01", 1)], parent_id,
    )
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "fuzzy"


def test_severity_bracket_falls_back_to_fuzzy() -> None:
    """[FULL-006] retest '鉴权绕过(高危)' vs parent '鉴权绕过' -> fuzzy."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["鉴权绕过"])
    load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("鉴权绕过(高危)", "鉴权绕过(高危)", 1)], parent_id,
    )
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "fuzzy"


def test_duochu_prefix_falls_back_to_fuzzy() -> None:
    """[FULL-006] retest '多处横向越权' vs parent '横向越权' -> fuzzy."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["横向越权"])
    load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("多处横向越权", "多处横向越权", 1)], parent_id,
    )
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "fuzzy"


def test_single_digit_name_is_not_stripped() -> None:
    """Guards [FULL-006]: 'XSS 2' is a real name, not an ordinal marker."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["XSS 2"])
    result = load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("XSS", "XSS", 1)], parent_id,
    )
    assert result.matched == 0
    assert result.unmatched == 1
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is None
    assert row[1] == "none"


def test_single_digit_parent_ordinals_fall_back_to_fuzzy() -> None:
    """[FULL-006 A] parent '纵向越权 1'/'纵向越权 2' + retest '纵向越权 01'."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["纵向越权 1", "纵向越权 2"])
    load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("纵向越权 01", "纵向越权 01", 1)], parent_id,
    )
    row = conn.execute(
        "SELECT r.vuln_id, r.match_confidence, v.vuln_name "
        "FROM v_retest_result r JOIN v_vulnerability v ON v.id = r.vuln_id"
    ).fetchone()
    assert row[1] == "fuzzy"
    assert row[2] == "纵向越权 1"


def test_single_digit_parent_ordinals_csp() -> None:
    """[FULL-006 A] same rule for '内容安全策略 CSP 缺失 1/2'."""
    conn = _conn()
    parent_id = _parent_with_names(
        conn, ["内容安全策略 CSP 缺失 1", "内容安全策略 CSP 缺失 2"]
    )
    load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("内容安全策略 CSP 缺失 01", "内容安全策略 CSP 缺失 01", 1)],
        parent_id,
    )
    row = conn.execute(
        "SELECT r.vuln_id, r.match_confidence, v.vuln_name "
        "FROM v_retest_result r JOIN v_vulnerability v ON v.id = r.vuln_id"
    ).fetchone()
    assert row[1] == "fuzzy"
    assert row[2] == "内容安全策略 CSP 缺失 1"


def test_lone_single_digit_parent_name_is_not_stripped() -> None:
    """Only one parent candidate -> never strip; 'XSS' must not match 'XSS 2'."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["XSS 2"])
    result = load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("XSS", "XSS", 1)], parent_id,
    )
    assert result.matched == 0
    assert result.unmatched == 1
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is None
    assert row[1] == "none"


def test_multiple_single_digit_parent_names_match_by_instance_index() -> None:
    """Two parent candidates collapse -> strip applies, pair by instance_index."""
    conn = _conn()
    parent_id = _parent_with_names(conn, ["XSS 1", "XSS 2"])
    load_retest_records(
        conn, "retest_norm.pdf",
        [_single_retest("XSS", "XSS", 1)], parent_id,
    )
    row = conn.execute(
        "SELECT r.vuln_id, r.match_confidence, v.vuln_name "
        "FROM v_retest_result r JOIN v_vulnerability v ON v.id = r.vuln_id"
    ).fetchone()
    assert row[1] == "fuzzy"
    assert row[2] == "XSS 1"
