"""Tests for the Phase 2 quality gate."""

from __future__ import annotations

from pathlib import Path

from pipeline.common.types import (
    CanonicalVulnRecord,
    ImageExtractionResult,
    ParsedDocument,
    RetestRecord,
)
from pipeline.phase2_parse.adapters.pdfplumber_adapter import PdfplumberAdapter
from pipeline.phase2_parse.field_extractor import extract_records
from pipeline.phase2_parse.quality_gate import evaluate_quality
from pipeline.phase2_parse.summary_locator import locate_summary
from pipeline.phase2_parse.text_block_locator import locate_text_blocks

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "pdfs"


def _empty_images() -> ImageExtractionResult:
    return ImageExtractionResult()


def test_no_vuln_report_is_no_vulnerabilities() -> None:
    doc = PdfplumberAdapter().parse(FIXTURES / "no_vuln.pdf")
    summary = locate_summary([page.text for page in doc.text_blocks])
    result = evaluate_quality([], summary, _empty_images(), doc, "pentest", {})
    assert result.parse_status == "no_vulnerabilities"


def test_kv_report_has_records_and_passes() -> None:
    doc = PdfplumberAdapter().parse(FIXTURES / "no_table.pdf")
    blocks = locate_text_blocks(doc, "pentest")
    records = extract_records(blocks, "no_table.pdf")
    summary = locate_summary([page.text for page in doc.text_blocks])
    result = evaluate_quality(records, summary, _empty_images(), doc, "pentest", {})
    assert len(records) == 2
    assert result.parse_status == "pass"
    assert result.summary["record_count"] == 2


def test_empty_without_zero_declaration_fails() -> None:
    doc = PdfplumberAdapter().parse(FIXTURES / "no_table.pdf")
    summary = {"declared_total": None, "declares_zero": False}
    result = evaluate_quality([], summary, _empty_images(), doc, "pentest", {})
    assert result.parse_status == "fail"


def _canonical(name: str, severity: str) -> CanonicalVulnRecord:
    return CanonicalVulnRecord(
        vuln_name=name,
        severity_raw=severity,
        source_file="x.pdf",
        source_page=1,
        instance_index=1,
        type_raw="测试",
        cvss_score=None,
        component=None,
        cwe_id=None,
        description_snippet="x",
        extraction_method="text_block",
        confidence="high",
    )


def _retest(name: str) -> RetestRecord:
    return RetestRecord(
        retest_report_path="x.pdf",
        raw_vuln_name=name,
        component=None,
        retest_status_raw="已修复",
        retest_status="fixed",
        retest_date="2026",
        evidence_snippet="已修复",
        source_page=1,
        instance_index=1,
        evidence_page=2,
        parent_vuln_name=name,
    )


def _doc() -> ParsedDocument:
    return ParsedDocument(
        source_file="x.pdf",
        page_count=1,
        text_blocks=[],
        tables=[],
        images=[],
        metadata={},
    )


def test_zero_extracted_with_declared_count_fails() -> None:
    result = evaluate_quality(
        [],
        {"declared_total": 5, "declares_zero": False},
        _empty_images(),
        _doc(),
        "pentest",
        {},
    )
    assert result.parse_status == "fail"
    assert result.summary["count_mismatch_warning"] is False


def test_pentest_aggregated_count_is_pass_with_warning() -> None:
    records = [_canonical(f"v{i}", "高危") for i in range(8)]
    result = evaluate_quality(
        records,
        {"declared_total": 27, "declares_zero": False},
        _empty_images(),
        _doc(),
        "pentest",
        {},
    )
    assert result.parse_status == "pass"
    assert result.summary["count_mismatch_warning"] is True
    assert result.summary["declared_count"] == 27
    assert result.summary["extracted_count"] == 8
    assert {check["id"] for check in result.checks} >= {
        "count_cross_check",
        "count_mismatch_warning",
    }


def test_retest_aggregated_count_is_pass_with_warning() -> None:
    records = [_retest(f"v{i}") for i in range(4)]
    result = evaluate_quality(
        records,
        {"declared_total": 27, "declares_zero": False},
        _empty_images(),
        _doc(),
        "retest",
        {},
    )
    assert result.parse_status == "pass"
    assert result.summary["count_mismatch_warning"] is True


def test_small_extraction_stays_pending_review() -> None:
    records = [_canonical(f"v{i}", "高危") for i in range(2)]
    result = evaluate_quality(
        records,
        {"declared_total": 5, "declares_zero": False},
        _empty_images(),
        _doc(),
        "pentest",
        {},
    )
    assert result.parse_status == "pending_review"
    assert result.summary["count_mismatch_warning"] is False


def test_moderate_mismatch_stays_pending_review() -> None:
    records = [_canonical(f"v{i}", "高危") for i in range(5)]
    result = evaluate_quality(
        records,
        {"declared_total": 7, "declares_zero": False},
        _empty_images(),
        _doc(),
        "pentest",
        {},
    )
    assert result.parse_status == "pending_review"
    assert result.summary["count_mismatch_warning"] is False
