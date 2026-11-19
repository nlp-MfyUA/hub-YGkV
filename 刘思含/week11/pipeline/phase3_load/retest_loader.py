"""Load retest results into SQLite (Phase 3, scheme B)."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from pipeline.common.types import RetestLoadResult, RetestRecord

LOGGER = logging.getLogger("phase3.retest_loader")

# [FULL-002] Parent pentest reports suffix repeated vuln names with a Chinese
# numeral (``越权访问一``/``越权访问二``) while retest reports use the bare name.
_CN_ORDINAL_RE = re.compile(r"[一二三四五六七八九十]+$")

# [FULL-003] Some retest reports inline the remediation state in the title
# (``弱口令（已修复）``); the parent carries the bare name.
_STATUS_SUFFIX_RE = re.compile(r"[（(](?:已修复|已整改|未修复|未整改)[）)]$")

# [FULL-006] The 市监局 retest template leaks instance numbering and severity
# into the title (``纵向越权 01``, ``鉴权绕过(高危)``, ``多处横向越权``).
# Kept deliberately narrow: ``XSS 2`` is a legitimate name, so only two-digit
# ordinal markers are stripped, and the severity bracket must be at the end.
_TWO_DIGIT_ORDINAL_RE = re.compile(r"\s*\d{2}$")
_SEVERITY_BRACKET_RE = re.compile(r"[（(](?:高危|中危|低危|超危|严重|信息)[）)]$")
_PREFIX_RE = re.compile(r"^多处")

# [FULL-006 A] Single-digit ordinal on the PARENT side only; applied
# conditionally inside ``_match_vuln_id`` when two or more parent names
# collapse onto the same stripped form.
_SINGLE_DIGIT_ORDINAL_RE = re.compile(r"\s*\d$")


def _now() -> str:
    """Return a UTC ISO timestamp with microsecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _upsert_retest_report(
    conn: sqlite3.Connection,
    retest_report_path: str,
    parent_report_id: Optional[int],
    now: str,
) -> int:
    """UPSERT the retest v_report and return its id."""
    conn.execute(
        """
        INSERT INTO v_report (
            report_name, report_type, parent_report_id, status,
            created_at, updated_at
        ) VALUES (?, 'retest', ?, 'active', ?, ?)
        ON CONFLICT(report_name) DO UPDATE SET
            report_type      = 'retest',
            parent_report_id = excluded.parent_report_id,
            status           = 'active',
            updated_at       = excluded.updated_at
        """,
        (retest_report_path, parent_report_id, now, now),
    )
    row = conn.execute(
        "SELECT id FROM v_report WHERE report_name = ?",
        (retest_report_path,),
    ).fetchone()
    if row is None:  # pragma: no cover - defensive
        raise RuntimeError(
            f"v_report upsert did not return a row: {retest_report_path}"
        )
    return int(row[0])


def _strip_status_suffix(name: str) -> str:
    """Drop a trailing ``（已修复）``/``(已整改)`` style status marker."""
    return _STATUS_SUFFIX_RE.sub("", name).strip()


def _normalize_name(name: str) -> str:
    """Canonical form used by the fuzzy tiers only.

    Strips the artefacts the upstream templates leak into titles: trailing
    status markers, trailing two-digit ordinals, trailing severity brackets and
    a leading ``多处``. Narrow on purpose - ``XSS 2`` must survive intact.
    """
    text = _STATUS_SUFFIX_RE.sub("", name)
    text = _SEVERITY_BRACKET_RE.sub("", text)
    text = _TWO_DIGIT_ORDINAL_RE.sub("", text)
    text = _PREFIX_RE.sub("", text)
    return text.strip()


def _ordinal_variants(name: str) -> set[str]:
    """All accepted normalisations of ``name`` for the fuzzy tiers."""
    variants = {
        _normalize_name(name),
        _CN_ORDINAL_RE.sub("", _normalize_name(name)),
        _normalize_name(_CN_ORDINAL_RE.sub("", name)),
    }
    variants.discard("")
    return variants


def _pick_candidate(
    candidates: list[tuple[int, int]],
    instance_index: int,
) -> Optional[int]:
    """Resolve a candidate set to one row id, or None when ambiguous.

    A single candidate is unambiguous. With several same-named instances the
    retest record must carry a matching ``instance_index``; picking the first
    row would silently bind the wrong vulnerability.
    """
    if len(candidates) == 1:
        return int(candidates[0][0])
    for row_id, candidate_index in candidates:
        if candidate_index == instance_index:
            return int(row_id)
    return None


def _match_vuln_id(
    conn: sqlite3.Connection,
    parent_report_id: Optional[int],
    retest_record: RetestRecord,
) -> tuple[Optional[int], str]:
    """Match a retest record to a specific parent vulnerability instance.

    Three tiers, cheapest first:

    1. exact  - ``raw_vuln_name = parent.vuln_name`` (original behaviour)
    2. fuzzy  - both sides stripped of a trailing Chinese ordinal ([FULL-002])
    3. fuzzy  - both sides stripped of a trailing status suffix ([FULL-003])
    """
    parent_vuln_name = retest_record.parent_vuln_name
    component = retest_record.component or ""
    if parent_report_id is None or not parent_vuln_name:
        return None, "none"

    # --- Tier 1: exact name match -------------------------------------
    candidates = conn.execute(
        """
        SELECT id, instance_index FROM v_vulnerability
        WHERE report_id = ?
          AND vuln_name = ?
          AND COALESCE(component, '') = ?
        ORDER BY instance_index
        """,
        (parent_report_id, parent_vuln_name, component),
    ).fetchall()
    if candidates:
        chosen = _pick_candidate(candidates, retest_record.instance_index)
        return (chosen, "exact") if chosen is not None else (None, "none")

    # --- Tier 2 + 3 + 4: normalized matches ----------------------------
    # [FULL-002] Chinese ordinals, [FULL-003] status suffixes,
    # [FULL-006] two-digit ordinals / severity brackets / 多处 prefix.
    wanted = _ordinal_variants(parent_vuln_name)
    if not wanted:
        return None, "none"

    rows = conn.execute(
        """
        SELECT id, vuln_name, instance_index FROM v_vulnerability
        WHERE report_id = ?
          AND COALESCE(component, '') = ?
        ORDER BY instance_index
        """,
        (parent_report_id, component),
    ).fetchall()

    fuzzy: list[tuple[int, int]] = []
    for row_id, vuln_name, row_index in rows:
        normalized = _normalize_name(vuln_name or "")
        if not normalized:
            continue
        if normalized in wanted or _CN_ORDINAL_RE.sub("", normalized) in wanted:
            fuzzy.append((row_id, row_index))

    if not fuzzy:
        # --- Tier 5: parent-side single-digit ordinals ([FULL-006 A]) ---
        # Some parents mark repeated vulns as ``纵向越权 1``/``纵向越权 2``
        # while the retest template writes ``纵向越权 01``/``02``. We only
        # strip a lone trailing digit from the PARENT name, and only when two
        # or more parent names collapse onto the same stripped form - that is
        # what makes it safe (``XSS 2`` alone is never touched).
        stripped_groups: dict[str, list[tuple[int, int]]] = {}
        for row_id, vuln_name, row_index in rows:
            normalized = _normalize_name(vuln_name or "")
            single = _CN_ORDINAL_RE.sub("", _SINGLE_DIGIT_ORDINAL_RE.sub("", normalized))
            if single and single != normalized:
                stripped_groups.setdefault(single, []).append((row_id, row_index))
        for stripped_name, group in stripped_groups.items():
            if len(group) > 1 and stripped_name in wanted:
                fuzzy.extend(group)

    if not fuzzy:
        return None, "none"
    chosen = _pick_candidate(fuzzy, retest_record.instance_index)
    return (chosen, "fuzzy") if chosen is not None else (None, "none")


def _supersede_missing(
    conn: sqlite3.Connection,
    retest_report_id: int,
    records: list[RetestRecord],
    now: str,
) -> int:
    """Soft-delete active retest rows not present in the current set."""
    keep = {
        (record.raw_vuln_name, record.component or "", record.instance_index)
        for record in records
    }
    existing = conn.execute(
        """
        SELECT id, raw_vuln_name, COALESCE(component, ''), instance_index
        FROM v_retest_result
        WHERE retest_report_id = ? AND status = 'active'
        """,
        (retest_report_id,),
    ).fetchall()
    superseded = 0
    for row_id, raw_vuln_name, component, instance_index in existing:
        if (raw_vuln_name, component, instance_index) in keep:
            continue
        conn.execute(
            """
            UPDATE v_retest_result
            SET status = 'superseded', updated_at = ?
            WHERE id = ?
            """,
            (now, row_id),
        )
        superseded += 1
    return superseded


def _upsert_retest_record(
    conn: sqlite3.Connection,
    retest_report_id: int,
    record: RetestRecord,
    vuln_id: Optional[int],
    match_confidence: str,
    now: str,
) -> bool:
    """UPSERT one retest record; return True when it already existed."""
    component = record.component or ""
    existing = conn.execute(
        """
        SELECT id FROM v_retest_result
        WHERE retest_report_id = ? AND raw_vuln_name = ? AND component = ?
          AND instance_index = ?
        """,
        (
            retest_report_id,
            record.raw_vuln_name,
            component,
            record.instance_index,
        ),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO v_retest_result (
            vuln_id, retest_report_id, raw_vuln_name, component,
            instance_index, retest_status, retest_status_raw, retest_date,
            evidence_snippet, evidence_page, source_page, match_confidence,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        ON CONFLICT(
            retest_report_id, raw_vuln_name, component, instance_index
        ) DO UPDATE SET
            vuln_id           = excluded.vuln_id,
            retest_status     = excluded.retest_status,
            retest_status_raw = excluded.retest_status_raw,
            retest_date       = excluded.retest_date,
            evidence_snippet  = excluded.evidence_snippet,
            evidence_page     = excluded.evidence_page,
            source_page       = excluded.source_page,
            match_confidence  = excluded.match_confidence,
            status            = 'active',
            updated_at        = excluded.updated_at
        """,
        (
            vuln_id,
            retest_report_id,
            record.raw_vuln_name,
            component,
            record.instance_index,
            record.retest_status,
            record.retest_status_raw,
            record.retest_date,
            record.evidence_snippet,
            record.evidence_page,
            record.source_page,
            match_confidence,
            now,
            now,
        ),
    )
    return existing is not None


def load_retest_records(
    conn: sqlite3.Connection,
    retest_report_path: str,
    retest_records: list[RetestRecord],
    parent_report_id: Optional[int],
) -> RetestLoadResult:
    """Synchronize one retest report into v_report + v_retest_result."""
    try:
        conn.execute("BEGIN")
        now = _now()
        retest_report_id = _upsert_retest_report(
            conn, retest_report_path, parent_report_id, now
        )
        superseded = _supersede_missing(conn, retest_report_id, retest_records, now)

        inserted = 0
        updated = 0
        matched = 0
        unmatched = 0
        for record in retest_records:
            vuln_id, confidence = _match_vuln_id(
                conn,
                parent_report_id,
                record,
            )
            if vuln_id is None:
                unmatched += 1
            else:
                matched += 1
            existed = _upsert_retest_record(
                conn,
                retest_report_id,
                record,
                vuln_id,
                confidence,
                _now(),
            )
            if existed:
                updated += 1
            else:
                inserted += 1

        conn.commit()
        return RetestLoadResult(
            report_id=retest_report_id,
            inserted=inserted,
            updated=updated,
            superseded=superseded,
            matched=matched,
            unmatched=unmatched,
            status="pass",
        )
    except Exception as exc:  # noqa: BLE001 - return failure, never swallow
        conn.rollback()
        LOGGER.error(
            "load_retest_records failed for %s: %s",
            retest_report_path,
            exc,
            exc_info=True,
        )
        return RetestLoadResult(
            report_id=None,
            inserted=0,
            updated=0,
            superseded=0,
            matched=0,
            unmatched=0,
            status="fail",
            error=str(exc),
        )
