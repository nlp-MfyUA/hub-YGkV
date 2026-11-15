"""Tests for image extraction, OCR and page-proximity linking."""

from __future__ import annotations

from pathlib import Path

from pipeline.common.types import (
    CanonicalVulnRecord,
    ImageBlock,
    ParsedDocument,
    RetestRecord,
)
from pipeline.phase2_parse.adapters.pdfplumber_adapter import PdfplumberAdapter
from pipeline.phase2_parse.image_extractor import extract_images

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "pdfs"


def test_extract_image_ocr_and_link(tmp_path: Path) -> None:
    doc = PdfplumberAdapter().parse(FIXTURES / "table_with_image.pdf")
    record = CanonicalVulnRecord(
        vuln_name="SQL Injection",
        severity_raw="High",
        source_file="table_with_image.pdf",
        source_page=1,
        type_raw=None,
        cvss_score=None,
        component=None,
        cwe_id=None,
        description_snippet="Login form is injectable.",
        extraction_method="text_block",
        confidence="high",
    )
    result = extract_images(
        doc,
        [record],
        source_file="table_with_image.pdf",
        output_image_dir=tmp_path,
        image_rules={
            "ocr_enabled": True,
            "ocr_languages": ["ch", "en"],
            "exclude_small_images": {
                "min_width": 300,
                "min_height": 150,
                "min_kb": 1,
            },
        },
        pdf_id="test",
    )
    assert len(result.image_records) == 1
    image = result.image_records[0]
    assert image.image_path == "test/2_0.png"
    assert (tmp_path / "2_0.png").is_file()
    assert image.ocr_text
    assert "OR" in image.ocr_text
    assert "1=1" in image.ocr_text
    assert image.linked_vuln_name == "SQL Injection"
    assert image.generated_description is None


def test_retest_image_links_by_evidence_page(tmp_path: Path) -> None:
    doc = ParsedDocument(
        source_file="retest.pdf",
        page_count=5,
        images=[
            ImageBlock(
                page=5,
                index_on_page=0,
                image_bytes=b"fake-image-bytes",
                ext="png",
                srcsize=(800, 600),
            )
        ],
    )
    record = RetestRecord(
        retest_report_path="retest.pdf",
        raw_vuln_name="逻辑漏洞-前端校验绕过",
        component=None,
        retest_status_raw="该漏洞已修复完成。",
        retest_status="fixed",
        retest_date="2026年2月-6月",
        evidence_snippet="该漏洞已修复完成。",
        source_page=2,
        evidence_page=5,
    )
    result = extract_images(
        doc,
        [record],
        source_file="retest.pdf",
        output_image_dir=tmp_path,
        image_rules={
            "ocr_enabled": False,
            "exclude_small_images": {
                "min_width": 300,
                "min_height": 150,
                "min_kb": 0,
            },
        },
        pdf_id="t",
    )
    assert len(result.image_records) == 1
    assert result.image_records[0].linked_vuln_name == record.raw_vuln_name
