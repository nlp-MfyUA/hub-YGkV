"""Load image evidence into SQLite, with FTS rebuild and verification."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from pipeline.common.types import ImageLoadResult, ImageRecord

LOGGER = logging.getLogger("phase3.image_loader")


class FTSInconsistencyError(RuntimeError):
    """Raised when v_image_evidence and its FTS index disagree."""


def _now() -> str:
    """Return a UTC ISO timestamp with microsecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _supersede_missing(
    conn: sqlite3.Connection,
    source_file: str,
    image_records: list[ImageRecord],
    now: str,
) -> int:
    """Soft-delete active images not present in the current set."""
    keep = {(record.source_page, record.image_index) for record in image_records}
    existing = conn.execute(
        """
        SELECT id, source_page, image_index
        FROM v_image_evidence
        WHERE source_file = ? AND status = 'active'
        """,
        (source_file,),
    ).fetchall()
    superseded = 0
    for row_id, source_page, image_index in existing:
        if (source_page, image_index) in keep:
            continue
        conn.execute(
            """
            UPDATE v_image_evidence
            SET status = 'superseded', updated_at = ?
            WHERE id = ?
            """,
            (now, row_id),
        )
        superseded += 1
    return superseded


def _upsert_image(
    conn: sqlite3.Connection,
    report_id: int,
    source_file: str,
    record: ImageRecord,
    now: str,
) -> bool:
    """UPSERT one image record; return True when it already existed."""
    existing = conn.execute(
        """
        SELECT id FROM v_image_evidence
        WHERE source_file = ? AND source_page = ? AND image_index = ?
        """,
        (source_file, record.source_page, record.image_index),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO v_image_evidence (
            report_id, source_file, source_page, image_index, image_path,
            image_type, ocr_text, ocr_confidence, linked_vuln_name,
            generated_description, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?)
        ON CONFLICT(source_file, source_page, image_index) DO UPDATE SET
            report_id            = excluded.report_id,
            image_path           = excluded.image_path,
            image_type           = excluded.image_type,
            ocr_text             = excluded.ocr_text,
            ocr_confidence       = excluded.ocr_confidence,
            linked_vuln_name     = excluded.linked_vuln_name,
            generated_description = NULL,
            status               = 'active',
            updated_at           = excluded.updated_at
        """,
        (
            report_id,
            source_file,
            record.source_page,
            record.image_index,
            record.image_path,
            record.image_type,
            record.ocr_text,
            record.ocr_confidence,
            record.linked_vuln_name,
            now,
            now,
        ),
    )
    return existing is not None


def _rebuild_and_verify_fts(conn: sqlite3.Connection, source_file: str) -> None:
    """Rebuild the FTS index and verify active-row consistency."""
    conn.execute(
        "INSERT INTO v_image_evidence_fts(v_image_evidence_fts) VALUES('rebuild')"
    )
    # Soft-deleted rows stay in the content table for audit, but must not be
    # searchable. Remove them from the FTS index after rebuild.
    superseded = conn.execute(
        """
        SELECT id, ocr_text, linked_vuln_name
        FROM v_image_evidence WHERE status = 'superseded'
        """
    ).fetchall()
    for row_id, ocr_text, linked_name in superseded:
        conn.execute(
            """
            INSERT INTO v_image_evidence_fts(
                v_image_evidence_fts, rowid, ocr_text, linked_vuln_name
            ) VALUES ('delete', ?, ?, ?)
            """,
            (row_id, ocr_text, linked_name),
        )
    active = conn.execute(
        """
        SELECT COUNT(*) FROM v_image_evidence
        WHERE status = 'active' AND source_file = ?
        """,
        (source_file,),
    ).fetchone()[0]
    # For an external-content FTS5 table, SELECT COUNT(*) on the virtual
    # table reads the content table, not the index. The shadow table
    # *_docsize is the authoritative count of indexed rows.
    indexed = conn.execute(
        """
        SELECT COUNT(*) FROM v_image_evidence_fts_docsize
        WHERE id IN (
            SELECT id FROM v_image_evidence
            WHERE status = 'active' AND source_file = ?
        )
        """,
        (source_file,),
    ).fetchone()[0]
    total_active = conn.execute(
        "SELECT COUNT(*) FROM v_image_evidence WHERE status = 'active'"
    ).fetchone()[0]
    total_indexed = conn.execute(
        "SELECT COUNT(*) FROM v_image_evidence_fts_docsize"
    ).fetchone()[0]
    if active != indexed or total_active != total_indexed:
        raise FTSInconsistencyError(
            f"FTS mismatch for {source_file}: "
            f"active={active}, indexed={indexed}, "
            f"total_active={total_active}, total_indexed={total_indexed}"
        )


def load_image_records(
    conn: sqlite3.Connection,
    report_id: int,
    source_file: str,
    image_records: list[ImageRecord],
) -> ImageLoadResult:
    """Synchronize one report's image records into v_image_evidence + FTS."""
    try:
        conn.execute("BEGIN")
        now = _now()
        superseded = _supersede_missing(conn, source_file, image_records, now)
        inserted = 0
        updated = 0
        for record in image_records:
            existed = _upsert_image(conn, report_id, source_file, record, _now())
            if existed:
                updated += 1
            else:
                inserted += 1

        _rebuild_and_verify_fts(conn, source_file)
        conn.commit()
        return ImageLoadResult(
            inserted=inserted,
            updated=updated,
            superseded=superseded,
            status="pass",
        )
    except FTSInconsistencyError:
        conn.rollback()
        LOGGER.error("FTS inconsistency while loading %s", source_file, exc_info=True)
        raise
    except Exception as exc:  # noqa: BLE001 - return failure, never swallow
        conn.rollback()
        LOGGER.error(
            "load_image_records failed for %s: %s",
            source_file,
            exc,
            exc_info=True,
        )
        return ImageLoadResult(
            inserted=0,
            updated=0,
            superseded=0,
            status="fail",
            error=str(exc),
        )
