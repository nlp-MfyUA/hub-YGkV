"""Tests for the pdfplumber adapter."""

from __future__ import annotations

from pathlib import Path

from pipeline.phase2_parse.adapters.pdfplumber_adapter import PdfplumberAdapter

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "pdfs"


def test_simple_table_has_one_table_and_no_image() -> None:
    doc = PdfplumberAdapter().parse(FIXTURES / "simple_table.pdf")
    assert doc.page_count == 1
    assert len(doc.tables) == 1
    assert doc.tables[0].page == 1
    assert doc.tables[0].headers == ["Severity", "Finding", "Component", "CWE"]
    assert doc.images == []


def test_table_with_image_has_table_on_page_one_and_image_on_page_two() -> None:
    doc = PdfplumberAdapter().parse(FIXTURES / "table_with_image.pdf")
    assert doc.page_count == 2
    assert len(doc.tables) == 1
    assert doc.tables[0].page == 1
    assert len(doc.images) == 1
    assert doc.images[0].page == 2
    assert doc.images[0].image_bytes


def test_no_table_has_text_and_no_tables() -> None:
    doc = PdfplumberAdapter().parse(FIXTURES / "no_table.pdf")
    assert doc.tables == []
    assert doc.text_blocks
    assert "Finding #1" in doc.text_blocks[0].text
