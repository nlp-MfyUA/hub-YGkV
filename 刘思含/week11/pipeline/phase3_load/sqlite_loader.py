"""Load canonical vulnerability records into SQLite."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Literal, Optional

from pipeline.common.types import CanonicalVulnRecord, LoadResult
from pipeline.phase3_load.normalizer import normalize_severity, normalize_type

LOGGER = logging.getLogger("phase3.loader")


def _now() -> str:
    """Return a UTC ISO timestamp with microsecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _upsert_report(
    conn: sqlite3.Connection,
    report_path: str,
    report_type: Literal["pentest", "retest"],
    parent_report_id: Optional[int],
    now: str,
) -> int:
    """UPSERT v_report and return its id."""
    conn.execute(
        """
        INSERT INTO v_report (
            report_name, report_type, parent_report_id, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'active', ?, ?)
        ON CONFLICT(report_name) DO UPDATE SET
            report_type      = excluded.report_type,
            parent_report_id = excluded.parent_report_id,
            status           = 'active',
            updated_at       = excluded.updated_at
        """,
        (report_path, report_type, parent_report_id, now, now),
    )
    row = conn.execute(
        "SELECT id FROM v_report WHERE report_name = ?", (report_path,)
    ).fetchone()
    if row is None:  # pragma: no cover - defensive
        raise RuntimeError(f"v_report upsert did not return a row: {report_path}")
    return int(row[0])


def _supersede_missing(
    conn: sqlite3.Connection,
    report_id: int,
    records: list[CanonicalVulnRecord],
    now: str,
) -> int:
    """Soft-delete active rows not present in the current record set."""
    keep = {
        (record.vuln_name, record.component or "", record.instance_index)
        for record in records
    }
    existing = conn.execute(
        """
        SELECT id, vuln_name, COALESCE(component, ''), instance_index
        FROM v_vulnerability
        WHERE report_id = ? AND status = 'active'
        """,
        (report_id,),
    ).fetchall()
    superseded = 0
    for row_id, vuln_name, component, instance_index in existing:
        if (vuln_name, component, instance_index) in keep:
            continue
        conn.execute(
            """
            UPDATE v_vulnerability
            SET status = 'superseded', updated_at = ?
            WHERE id = ?
            """,
            (now, row_id),
        )
        superseded += 1
    return superseded


def _upsert_record(
    conn: sqlite3.Connection,
    report_id: int,
    report_path: str,
    record: CanonicalVulnRecord,
    severity: str,
    type_code: str,
    type_name: str,
    now: str,
) -> bool:
    """UPSERT one vulnerability; return True when it already existed."""
    component = record.component or ""
    source_file = record.source_file or report_path
    existing = conn.execute(
        """
        SELECT id FROM v_vulnerability
        WHERE source_file = ? AND vuln_name = ? AND component = ?
          AND instance_index = ?
        """,
        (source_file, record.vuln_name, component, record.instance_index),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO v_vulnerability (
            report_id, source_file, vuln_name, instance_index,
            severity, severity_raw, type_code, type_name, cvss_score,
            component, cwe_id, description_snippet, source_page,
            extraction_method, confidence, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        ON CONFLICT(source_file, vuln_name, component, instance_index) DO UPDATE SET
            report_id           = excluded.report_id,
            severity            = excluded.severity,
            severity_raw        = excluded.severity_raw,
            type_code           = excluded.type_code,
            type_name           = excluded.type_name,
            cvss_score          = excluded.cvss_score,
            cwe_id              = excluded.cwe_id,
            description_snippet = excluded.description_snippet,
            source_page         = excluded.source_page,
            extraction_method   = excluded.extraction_method,
            confidence          = excluded.confidence,
            status              = 'active',
            updated_at          = CASE
                WHEN v_vulnerability.report_id IS excluded.report_id
                 AND v_vulnerability.severity IS excluded.severity
                 AND v_vulnerability.severity_raw IS excluded.severity_raw
                 AND v_vulnerability.type_code IS excluded.type_code
                 AND v_vulnerability.type_name IS excluded.type_name
                 AND v_vulnerability.cvss_score IS excluded.cvss_score
                 AND v_vulnerability.cwe_id IS excluded.cwe_id
                 AND v_vulnerability.description_snippet IS excluded.description_snippet
                 AND v_vulnerability.source_page IS excluded.source_page
                 AND v_vulnerability.extraction_method IS excluded.extraction_method
                 AND v_vulnerability.confidence IS excluded.confidence
                 AND v_vulnerability.status = 'active'
                THEN v_vulnerability.updated_at
                ELSE excluded.updated_at
            END
        """,
        (
            report_id,
            source_file,
            record.vuln_name,
            record.instance_index,
            severity,
            record.severity_raw,
            type_code,
            type_name,
            record.cvss_score,
            component,
            record.cwe_id,
            record.description_snippet,
            record.source_page,
            record.extraction_method,
            record.confidence,
            now,
            now,
        ),
    )
    return existing is not None


def load_file_records(
    conn: sqlite3.Connection,
    report_path: str,
    report_type: Literal["pentest", "retest"],
    records: list[CanonicalVulnRecord],
    severity_map: dict[str, str],
    type_catalog: dict[str, tuple[str, str]],
    type_rules: list[dict] | None = None,
    parent_report_id: Optional[int] = None,
) -> LoadResult:
    """Synchronize one report's records into v_report + v_vulnerability."""
    try:
        conn.execute("BEGIN")
        now = _now()
        report_id = _upsert_report(
            conn, report_path, report_type, parent_report_id, now
        )
        superseded = _supersede_missing(conn, report_id, records, now)

        if not records:
            if report_type == "pentest":
                conn.commit()
                return LoadResult(
                    report_id=report_id,
                    inserted=0,
                    updated=0,
                    superseded=superseded,
                    status="skipped_no_vulns",
                )
            conn.commit()
            return LoadResult(
                report_id=report_id,
                inserted=0,
                updated=0,
                superseded=superseded,
                status="pass",
            )

        inserted = 0
        updated = 0
        for record in records:
            if not record.vuln_name or not str(record.vuln_name).strip():
                raise ValueError(f"empty vuln_name in {record.source_file}")
            severity = normalize_severity(record.severity_raw, severity_map)
            type_code, type_name = normalize_type(
                record.type_raw,
                type_catalog,
                type_rules,
                fallback_name=record.vuln_name,
            )
            existed = _upsert_record(
                conn,
                report_id,
                report_path,
                record,
                severity,
                type_code,
                type_name,
                _now(),
            )
            if existed:
                updated += 1
            else:
                inserted += 1

        conn.commit()
        return LoadResult(
            report_id=report_id,
            inserted=inserted,
            updated=updated,
            superseded=superseded,
            status="pass",
        )
    except ValueError:
        conn.rollback()
        LOGGER.error("invalid record while loading %s", report_path, exc_info=True)
        raise
    except Exception as exc:  # noqa: BLE001 - return failure, never swallow
        conn.rollback()
        LOGGER.error(
            "load_file_records failed for %s: %s",
            report_path,
            exc,
            exc_info=True,
        )
        return LoadResult(
            report_id=None,
            inserted=0,
            updated=0,
            superseded=0,
            status="fail",
            error=str(exc),
        )
