"""Phase 3 entry point: load pentest and retest batches into SQLite."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from pipeline.common.types import (
    CanonicalVulnRecord,
    ImageRecord,
    LoadResult,
    ParseResult,
    RetestRecord,
)
from pipeline.phase3_load.image_loader import (
    FTSInconsistencyError,
    load_image_records,
)
from pipeline.phase3_load.retest_loader import load_retest_records
from pipeline.phase3_load.sqlite_loader import load_file_records

LOGGER = logging.getLogger("phase3.run_load")

DELIVERABLES_ROOT = Path("deliverables")
REPORT_TYPE_RETEST = "回归测试报告"
SUFFIX_PEN = re.compile(r"渗透测试报告-\d{6}-v\d+\.\d+\.pdf$")
SUFFIX_REG = re.compile(r"渗透测试回归测试报告-\d{6}-v\d+\.\d+\.pdf$")


def _now() -> str:
    """Return a UTC ISO timestamp with microsecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _report_type(relative_path: str) -> str:
    """Infer report type from the path."""
    return "retest" if REPORT_TYPE_RETEST in relative_path else "pentest"


def _parse_report_path(relative_path: str) -> tuple[str, str, str]:
    """Return (round, team, normalized system) from a relative path."""
    path = Path(relative_path)
    parts = path.parts
    round_name = parts[0] if parts else ""
    team = parts[1] if len(parts) > 1 else ""
    name = path.name
    rest = name[len("一分中心") :] if name.startswith("一分中心") else name
    team_index = rest.find("团队")
    remainder = rest[team_index + 2 :] if team_index >= 0 else rest
    pattern = SUFFIX_REG if REPORT_TYPE_RETEST in name else SUFFIX_PEN
    match = pattern.search(remainder)
    system = remainder[: match.start()] if match else remainder
    return round_name, team, re.sub(r"[^\w]+", "", system.lower())


def _find_parent_report_id(
    conn: sqlite3.Connection, relative_path: str
) -> Optional[int]:
    """Find the unique same-round/team/system pentest report id."""
    round_name, team, system = _parse_report_path(relative_path)
    candidates = []
    for report_id, report_name in conn.execute(
        """
        SELECT id, report_name FROM v_report
        WHERE report_type = 'pentest' AND status = 'active'
        """
    ):
        p_round, p_team, p_system = _parse_report_path(report_name)
        if (p_round, p_team, p_system) == (round_name, team, system):
            candidates.append(int(report_id))
    return candidates[0] if len(candidates) == 1 else None


def _load_severity_map(config_dir: Path) -> dict[str, str]:
    """Load the complete severity mapping YAML."""
    path = Path(config_dir) / "severity_map.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid severity map: {path}")
    return {str(key): str(value) for key, value in data.items()}


def _load_type_catalog(
    conn: sqlite3.Connection,
) -> dict[str, tuple[str, str]]:
    """Load type_code -> (type_name, category) from v_type_catalog."""
    return {
        row[0]: (row[1], row[2] or "")
        for row in conn.execute(
            "SELECT type_code, type_name, category FROM v_type_catalog"
        )
    }


def _load_type_rules(config_dir: Path) -> list[dict]:
    """Load keyword rules from config/type_mapping.yaml."""
    path = Path(config_dir) / "type_mapping.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise ValueError(f"invalid type mapping: {path}")
    return rules


def _read_json(path: Path) -> list[dict]:
    """Read a JSON array file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _image_records(output_path: Path) -> list[ImageRecord]:
    """Read image_records.json from a parsed report directory."""
    path = output_path / "image_records.json"
    if not path.is_file():
        return []
    return [ImageRecord(**item) for item in _read_json(path)]


def _pdf_metadata(relative_path: str, output_path: Path, config_dir: Path) -> dict:
    """Collect pdf_index metadata for one report."""
    pdf_path = DELIVERABLES_ROOT / relative_path
    if pdf_path.is_file():
        stat = pdf_path.stat()
        file_size = stat.st_size
        mtime_ns = stat.st_mtime_ns
        digest = hashlib.sha256()
        with pdf_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        content_hash = digest.hexdigest()
    else:
        file_size = 0
        mtime_ns = 0
        content_hash = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()

    parser_name = "pdfplumber"
    parser_version = ""
    raw_path = output_path / "raw_parsed.json"
    if raw_path.is_file():
        metadata = json.loads(raw_path.read_text(encoding="utf-8")).get("metadata", {})
        parser_name = metadata.get("adapter", parser_name)
        parser_version = metadata.get("adapter_version", parser_version)

    version_path = Path(config_dir) / "pipeline_version.txt"
    pipeline_version = (
        version_path.read_text(encoding="utf-8").strip()
        if version_path.is_file()
        else "1.0.0"
    )
    return {
        "file_size": file_size,
        "mtime_ns": mtime_ns,
        "content_hash": content_hash,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "pipeline_version": pipeline_version,
        "last_processed_at": _now(),
    }


def _upsert_pdf_index(
    conn: sqlite3.Connection,
    batch: ParseResult,
    load_status: str,
    config_dir: Path,
) -> None:
    """Insert/update pdf_index for one report."""
    try:
        output_path = Path(batch.output_path)
        metadata = _pdf_metadata(batch.relative_path, output_path, config_dir)
        conn.execute(
            """
            INSERT INTO pdf_index (
                relative_path, file_size, mtime_ns, content_hash,
                parser_name, parser_version, pipeline_version,
                parse_status, load_status, last_processed_at, last_batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(relative_path) DO UPDATE SET
                parse_status      = excluded.parse_status,
                load_status       = excluded.load_status,
                last_processed_at = excluded.last_processed_at
            """,
            (
                batch.relative_path,
                metadata["file_size"],
                metadata["mtime_ns"],
                metadata["content_hash"],
                metadata["parser_name"],
                metadata["parser_version"],
                metadata["pipeline_version"],
                batch.parse_status,
                load_status,
                metadata["last_processed_at"],
            ),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - index update must not hide report result
        conn.rollback()
        LOGGER.error(
            "pdf_index update failed for %s: %s",
            batch.relative_path,
            exc,
            exc_info=True,
        )


def _load_images_once(
    conn: sqlite3.Connection,
    report_id: int,
    batch: ParseResult,
) -> bool:
    """Load images once; return True on success."""
    images = _image_records(Path(batch.output_path))
    result = load_image_records(conn, report_id, batch.relative_path, images)
    return result.status == "pass"


def _load_images_with_retry(
    conn: sqlite3.Connection, report_id: int, batch: ParseResult
) -> bool:
    """Load images, retrying once for non-FTS failures."""
    try:
        if _load_images_once(conn, report_id, batch):
            return True
        LOGGER.warning("image load failed, retrying once: %s", batch.relative_path)
        return _load_images_once(conn, report_id, batch)
    except FTSInconsistencyError:
        LOGGER.error(
            "FTS inconsistency, no retry: %s",
            batch.relative_path,
            exc_info=True,
        )
        return False


def _load_pentest(
    conn: sqlite3.Connection,
    batch: ParseResult,
    severity_map: dict[str, str],
    type_catalog: dict[str, tuple[str, str]],
    config_dir: Path,
    type_rules: list[dict] | None = None,
) -> LoadResult:
    """Load a pentest batch, including the no_vulnerabilities branch."""
    records = [
        CanonicalVulnRecord(**item)
        for item in _read_json(Path(batch.output_path) / "canonical_records.json")
    ]
    try:
        result = load_file_records(
            conn,
            batch.relative_path,
            "pentest",
            records,
            severity_map,
            type_catalog,
            type_rules=type_rules,
        )
        if result.status == "fail":
            LOGGER.warning(
                "pentest load failed, retrying once: %s", batch.relative_path
            )
            result = load_file_records(
                conn,
                batch.relative_path,
                "pentest",
                records,
                severity_map,
                type_catalog,
                type_rules=type_rules,
            )
    except ValueError:
        LOGGER.error(
            "invalid pentest records, no retry: %s",
            batch.relative_path,
            exc_info=True,
        )
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return LoadResult(None, 0, 0, 0, "fail", "invalid_record")

    if result.status == "fail":
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return result

    if result.status == "skipped_no_vulns":
        _upsert_pdf_index(conn, batch, "skipped_no_vulns", config_dir)
        return result

    if result.report_id is None:
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return LoadResult(None, 0, 0, 0, "fail", "missing_report_id")

    if not _load_images_with_retry(conn, result.report_id, batch):
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return LoadResult(
            result.report_id,
            result.inserted,
            result.updated,
            result.superseded,
            "fail",
            "image_load_failed",
        )

    _upsert_pdf_index(conn, batch, "pass", config_dir)
    return result


def _load_retest(
    conn: sqlite3.Connection,
    batch: ParseResult,
    config_dir: Path,
) -> LoadResult:
    """Load a retest batch, resolving its parent report first."""
    records = [
        RetestRecord(**item)
        for item in _read_json(Path(batch.output_path) / "retest_records.json")
    ]
    parent_report_id = _find_parent_report_id(conn, batch.relative_path)
    result = load_retest_records(conn, batch.relative_path, records, parent_report_id)
    if result.status == "fail":
        LOGGER.warning("retest load failed, retrying once: %s", batch.relative_path)
        result = load_retest_records(
            conn, batch.relative_path, records, parent_report_id
        )
    if result.status == "fail":
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return LoadResult(None, 0, 0, 0, "fail", result.error or "retest_load_failed")

    if result.report_id is None:
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return LoadResult(None, 0, 0, 0, "fail", "missing_report_id")

    if not _load_images_with_retry(conn, result.report_id, batch):
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return LoadResult(
            result.report_id,
            result.inserted,
            result.updated,
            result.superseded,
            "fail",
            "image_load_failed",
        )

    _upsert_pdf_index(conn, batch, "pass", config_dir)
    return LoadResult(
        report_id=result.report_id,
        inserted=result.inserted,
        updated=result.updated,
        superseded=result.superseded,
        status="pass",
    )


def _load_no_vulnerabilities(
    conn: sqlite3.Connection,
    batch: ParseResult,
    severity_map: dict[str, str],
    type_catalog: dict[str, tuple[str, str]],
    config_dir: Path,
) -> LoadResult:
    """Write v_report only for a no_vulnerabilities pentest report."""
    result = load_file_records(
        conn,
        batch.relative_path,
        "pentest",
        [],
        severity_map,
        type_catalog,
    )
    if result.status == "fail":
        LOGGER.warning(
            "no_vulnerabilities report load failed, retrying once: %s",
            batch.relative_path,
        )
        result = load_file_records(
            conn,
            batch.relative_path,
            "pentest",
            [],
            severity_map,
            type_catalog,
        )
    if result.status == "fail":
        _upsert_pdf_index(conn, batch, "fail", config_dir)
        return result
    _upsert_pdf_index(conn, batch, "skipped_no_vulns", config_dir)
    return result


def run_load(
    parsed_batches: list[ParseResult],
    db_path: Path,
    config_dir: Path,
    connection: Optional[sqlite3.Connection] = None,
) -> list[LoadResult]:
    """Load pentest batches first, then retest batches."""
    owns_connection = connection is None
    conn = connection or sqlite3.connect(db_path)
    try:
        severity_map = _load_severity_map(config_dir)
        type_catalog = _load_type_catalog(conn)
        type_rules = _load_type_rules(config_dir)
        pentest_batches = [
            batch
            for batch in parsed_batches
            if _report_type(batch.relative_path) == "pentest"
        ]
        retest_batches = [
            batch
            for batch in parsed_batches
            if _report_type(batch.relative_path) == "retest"
        ]

        results: list[LoadResult] = []
        for batch in pentest_batches + retest_batches:
            report_type = _report_type(batch.relative_path)
            if batch.parse_status == "pending_review":
                LOGGER.warning("skip pending_review: %s", batch.relative_path)
                results.append(
                    LoadResult(None, 0, 0, 0, "skipped_pending_review", "pending_review")
                )
                continue
            if batch.parse_status == "fail":
                LOGGER.error("skip parse fail: %s", batch.relative_path)
                _upsert_pdf_index(conn, batch, "fail", config_dir)
                results.append(LoadResult(None, 0, 0, 0, "fail", "parse_failed"))
                continue
            if batch.parse_status == "no_vulnerabilities" and report_type == "pentest":
                results.append(
                    _load_no_vulnerabilities(
                        conn, batch, severity_map, type_catalog, config_dir
                    )
                )
                continue
            if report_type == "pentest":
                results.append(
                    _load_pentest(
                        conn,
                        batch,
                        severity_map,
                        type_catalog,
                        config_dir,
                        type_rules,
                    )
                )
            else:
                results.append(_load_retest(conn, batch, config_dir))
        return results
    finally:
        if owns_connection:
            conn.close()
