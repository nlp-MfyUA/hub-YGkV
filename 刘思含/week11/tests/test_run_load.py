"""Tests for the Phase 3 run_load orchestrator."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pipeline.common.types import (
    CanonicalVulnRecord,
    ParseResult,
    RetestRecord,
)
from pipeline.phase3_load.run_load import run_load

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app" / "db" / "schema.sql"
CONFIG = ROOT / "pipeline" / "config"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _canonical(name: str, source_file: str) -> CanonicalVulnRecord:
    return CanonicalVulnRecord(
        vuln_name=name,
        severity_raw="高危",
        source_file=source_file,
        source_page=1,
        instance_index=1,
        type_raw="SQL 注入",
        cvss_score=None,
        component=None,
        cwe_id=None,
        description_snippet="test",
        extraction_method="text_block",
        confidence="high",
    )


def _retest(name: str, report_path: str) -> RetestRecord:
    return RetestRecord(
        retest_report_path=report_path,
        raw_vuln_name=name,
        component=None,
        retest_status_raw="该漏洞已修复完成。",
        retest_status="fixed",
        retest_date="2026年2月-6月",
        evidence_snippet="该漏洞已修复完成。",
        source_page=5,
        instance_index=1,
        evidence_page=12,
        parent_vuln_name=name,
    )


def _batch(
    tmp_path: Path,
    name: str,
    relative_path: str,
    report_type: str,
    parse_status: str,
    canonical: list[CanonicalVulnRecord] | None = None,
    retest: list[RetestRecord] | None = None,
) -> ParseResult:
    output_dir = tmp_path / name
    output_dir.mkdir()
    canonical = canonical or []
    retest = retest or []
    (output_dir / "canonical_records.json").write_text(
        json.dumps([item.to_dict() for item in canonical], ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "retest_records.json").write_text(
        json.dumps([item.to_dict() for item in retest], ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "image_records.json").write_text("[]", encoding="utf-8")
    (output_dir / "raw_parsed.json").write_text(
        json.dumps({"metadata": {"adapter": "pdfplumber", "adapter_version": "test"}}),
        encoding="utf-8",
    )
    return ParseResult(
        relative_path=relative_path,
        report_type=report_type,  # type: ignore[arg-type]
        parse_status=parse_status,
        output_path=output_dir.as_posix(),
        record_count=len(canonical),
        retest_count=len(retest),
        image_count=0,
        ocr_success_count=0,
        linked_count=0,
    )


def test_two_pass_order_pentest_before_retest(tmp_path: Path) -> None:
    conn = _conn()
    pentest_path = (
        "第一轮渗透测试/团队A/渗透测试报告/"
        "一分中心团队A系统A渗透测试报告-202606-v1.0.pdf"
    )
    retest_path = (
        "第一轮渗透测试/团队A/回归测试报告/"
        "一分中心团队A系统A渗透测试回归测试报告-202606-v1.0.pdf"
    )
    retest_batch = _batch(
        tmp_path,
        "retest",
        retest_path,
        "retest",
        "pass",
        retest=[_retest("漏洞A", retest_path)],
    )
    pentest_batch = _batch(
        tmp_path,
        "pentest",
        pentest_path,
        "pentest",
        "pass",
        canonical=[_canonical("漏洞A", pentest_path)],
    )
    run_load(
        [retest_batch, pentest_batch],
        Path(":memory:"),
        CONFIG,
        connection=conn,
    )
    rows = conn.execute("SELECT id, report_type FROM v_report ORDER BY id").fetchall()
    assert rows == [(1, "pentest"), (2, "retest")]
    confidence = conn.execute(
        "SELECT match_confidence FROM v_retest_result"
    ).fetchone()[0]
    assert confidence == "exact"


def test_no_vulnerabilities_writes_report_only(tmp_path: Path) -> None:
    conn = _conn()
    path = (
        "第一轮渗透测试/团队B/渗透测试报告/"
        "一分中心团队B系统B渗透测试报告-202606-v1.0.pdf"
    )
    batch = _batch(tmp_path, "novuln", path, "pentest", "no_vulnerabilities")
    run_load([batch], Path(":memory:"), CONFIG, connection=conn)
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM v_vulnerability").fetchone()[0] == 0
    status = conn.execute(
        "SELECT load_status FROM pdf_index WHERE relative_path = ?", (path,)
    ).fetchone()[0]
    assert status == "skipped_no_vulns"


def test_pending_review_keeps_existing_index_row(tmp_path: Path) -> None:
    conn = _conn()
    path = (
        "第一轮渗透测试/团队C/渗透测试报告/"
        "一分中心团队C系统C渗透测试报告-202606-v1.0.pdf"
    )
    conn.execute(
        """
        INSERT INTO pdf_index (
            relative_path, file_size, mtime_ns, content_hash,
            parser_name, parser_version, pipeline_version,
            parse_status, load_status, last_processed_at, last_batch_id
        ) VALUES (?, 1, 1, 'hash', 'pdfplumber', 'test', '1.0.0',
                  'pending_review', 'orphaned', '2026-01-01T00:00:00+00:00', NULL)
        """,
        (path,),
    )
    conn.commit()
    batch = _batch(tmp_path, "pending", path, "pentest", "pending_review")
    run_load([batch], Path(":memory:"), CONFIG, connection=conn)
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 0
    row = conn.execute(
        """
        SELECT parse_status, load_status, last_processed_at
        FROM pdf_index WHERE relative_path = ?
        """,
        (path,),
    ).fetchone()
    assert row is not None
    assert row[0] == "pending_review"
    assert row[1] == "orphaned"
    assert row[2] == "2026-01-01T00:00:00+00:00"


def test_value_error_marks_fail_without_retry(tmp_path: Path) -> None:
    conn = _conn()
    path = (
        "第一轮渗透测试/团队D/渗透测试报告/"
        "一分中心团队D系统D渗透测试报告-202606-v1.0.pdf"
    )
    batch = _batch(
        tmp_path,
        "invalid",
        path,
        "pentest",
        "pass",
        canonical=[_canonical("", path)],
    )
    run_load([batch], Path(":memory:"), CONFIG, connection=conn)
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 0
    status = conn.execute(
        "SELECT load_status FROM pdf_index WHERE relative_path = ?", (path,)
    ).fetchone()[0]
    assert status == "fail"


def test_retest_without_parent_is_unmatched(tmp_path: Path) -> None:
    conn = _conn()
    path = (
        "第一轮渗透测试/团队E/回归测试报告/"
        "一分中心团队E系统E渗透测试回归测试报告-202606-v1.0.pdf"
    )
    batch = _batch(
        tmp_path,
        "orphan_retest",
        path,
        "retest",
        "pass",
        retest=[_retest("漏洞E", path)],
    )
    run_load([batch], Path(":memory:"), CONFIG, connection=conn)
    assert conn.execute("SELECT COUNT(*) FROM v_report").fetchone()[0] == 1
    row = conn.execute(
        "SELECT vuln_id, match_confidence FROM v_retest_result"
    ).fetchone()
    assert row[0] is None
    assert row[1] == "none"
