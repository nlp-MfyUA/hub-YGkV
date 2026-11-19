"""Tests for the image evidence loader and FTS consistency."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pipeline.common.types import ImageRecord
from pipeline.phase3_load.image_loader import load_image_records

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "app" / "db" / "schema.sql"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        INSERT INTO v_report
            (report_name, report_type, status, created_at, updated_at)
        VALUES ('image_test.pdf', 'pentest', 'active', '2026-01-01', '2026-01-01')
        """
    )
    conn.commit()
    return conn


def _records() -> list[ImageRecord]:
    return [
        ImageRecord(
            source_file="image_test.pdf",
            source_page=page,
            image_index=0,
            image_path=f"test/{page}_0.png",
            image_type="screenshot",
            ocr_text=f"ocr text {page}",
            ocr_confidence="high",
            linked_vuln_name=None,
        )
        for page in (1, 2, 3)
    ]


def _load(conn: sqlite3.Connection, records: list[ImageRecord]):
    return load_image_records(conn, 1, "image_test.pdf", records)


def test_first_write_three_images_and_fts() -> None:
    conn = _conn()
    result = _load(conn, _records())
    assert result.status == "pass"
    assert result.inserted == 3
    assert conn.execute("SELECT COUNT(*) FROM v_image_evidence").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM v_image_evidence_fts").fetchone()[0] == 3
    generated = conn.execute(
        "SELECT generated_description FROM v_image_evidence"
    ).fetchall()
    assert all(row[0] is None for row in generated)


def test_duplicate_write_does_not_duplicate() -> None:
    conn = _conn()
    records = _records()
    _load(conn, records)
    result = _load(conn, records)
    assert result.inserted == 0
    assert result.updated == 3
    assert conn.execute("SELECT COUNT(*) FROM v_image_evidence").fetchone()[0] == 3


def test_update_ocr_text_is_reflected_in_fts() -> None:
    conn = _conn()
    records = _records()
    _load(conn, records)
    row_id = conn.execute(
        """
        SELECT id FROM v_image_evidence
        WHERE source_file='image_test.pdf' AND source_page=1 AND image_index=0
        """
    ).fetchone()[0]
    records[0] = ImageRecord(**{**records[0].to_dict(), "ocr_text": "updated OCR text"})
    _load(conn, records)
    fts_text = conn.execute(
        "SELECT ocr_text FROM v_image_evidence_fts WHERE rowid = ?",
        (row_id,),
    ).fetchone()[0]
    assert fts_text == "updated OCR text"


def test_difference_soft_delete_and_fts_active_consistency() -> None:
    conn = _conn()
    records = _records()
    _load(conn, records)
    result = _load(conn, records[:2])
    assert result.superseded == 1
    status = conn.execute(
        """
        SELECT status FROM v_image_evidence
        WHERE source_file='image_test.pdf' AND source_page=3
        """
    ).fetchone()[0]
    assert status == "superseded"
    active = conn.execute(
        """
        SELECT COUNT(*) FROM v_image_evidence
        WHERE status='active' AND source_file='image_test.pdf'
        """
    ).fetchone()[0]
    indexed_active = conn.execute(
        """
        SELECT COUNT(*) FROM v_image_evidence_fts_docsize
        WHERE id IN (
            SELECT id FROM v_image_evidence
            WHERE status='active' AND source_file='image_test.pdf'
        )
        """
    ).fetchone()[0]
    assert active == indexed_active == 2
    assert (
        conn.execute("SELECT COUNT(*) FROM v_image_evidence_fts_docsize").fetchone()[0]
        == 2
    )


def test_fts_active_count_matches_evidence() -> None:
    conn = _conn()
    _load(conn, _records())
    active = conn.execute(
        """
        SELECT COUNT(*) FROM v_image_evidence
        WHERE status='active' AND source_file='image_test.pdf'
        """
    ).fetchone()[0]
    indexed_active = conn.execute(
        """
        SELECT COUNT(*) FROM v_image_evidence_fts_docsize
        WHERE id IN (
            SELECT id FROM v_image_evidence
            WHERE status='active' AND source_file='image_test.pdf'
        )
        """
    ).fetchone()[0]
    assert active == indexed_active == 3
