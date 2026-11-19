"""Image evidence search tool backed by FTS5 plus a LIKE fallback."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from agents import function_tool

MAX_LIMIT = 10
MAX_OCR_CHARS = 1000
MIN_FTS_CHARS = 3

_SELECT_COLUMNS = """
        SELECT i.id, i.source_file, i.source_page, i.image_index,
               i.image_path, i.image_type, i.ocr_text, i.ocr_confidence,
               i.linked_vuln_name, i.updated_at
        FROM v_image_evidence i
        WHERE i.status = 'active'
"""


def _db_path() -> Path:
    """Return the database path from VULN_DB_PATH."""
    return Path(os.environ.get("VULN_DB_PATH", "app/db/vuln.db"))


def _connection_uri(db_path: Path) -> str:
    """Build the read-only SQLite URI."""
    return f"{db_path.resolve().as_uri()}?mode=ro"


def escape_fts_term(term: str) -> str:
    """Quote one FTS5 term, escaping embedded double quotes (P-FTS-003)."""
    return '"' + str(term).replace('"', '""') + '"'


def build_fts_query(keywords: list[str]) -> str:
    """Turn keywords into an FTS5 query using OR semantics."""
    terms = [escape_fts_term(keyword) for keyword in keywords if keyword]
    return " OR ".join(terms)


def escape_like_literal(value: str) -> str:
    """Escape LIKE wildcards and add surrounding wildcards.

    The escape character is a single backslash. The caller must pair the
    returned pattern with ``ESCAPE '\\'`` in SQL.
    """
    escaped = (
        value.replace(chr(92), chr(92) * 2)
        .replace("%", chr(92) + "%")
        .replace("_", chr(92) + "_")
    )
    return f"%{escaped}%"


def _vuln_clause(vuln_name: str | None) -> tuple[str, list[Any]]:
    """Return the SQL fragment and params for a vuln_name filter.

    The filter is applied in SQL before ``LIMIT`` so later reports are not
    cut off by ``ORDER BY id LIMIT n``.
    """
    if not vuln_name:
        return "", []
    return (
        " AND i.linked_vuln_name LIKE ? ESCAPE '\\'",
        [escape_like_literal(vuln_name)],
    )

def _source_file_clause(source_file: str | None) -> tuple[str, list[Any]]:
    """Return the SQL fragment and params for a source_file (report) filter.

    ``source_file`` is a path fragment — callers pass a team name, a system
    name, or part of the report path. Filtering happens in SQL before
    ``LIMIT`` so a specific report's evidence is not pushed out of the top
    ``limit`` rows by other reports (see [IMG-005]).
    """
    if not source_file:
        return "", []
    return (
        " AND i.source_file LIKE ? ESCAPE '\\'",
        [escape_like_literal(source_file)],
    )

def _filters(
    vuln_name: str | None,
    source_file: str | None,
) -> tuple[str, list[Any]]:
    """Combine filters in a stable order: vuln_name, then source_file."""
    clause, params = _vuln_clause(vuln_name)
    more_clause, more_params = _source_file_clause(source_file)
    return clause + more_clause, params + more_params


def _fetch_fts(
    conn: sqlite3.Connection,
    fts_query: str,
    vuln_name: str | None,
    limit: int,
    source_file: str | None = None,
) -> list[tuple]:
    """FTS5 candidates, optionally constrained by vuln_name / source_file."""
    sql = _SELECT_COLUMNS
    params: list[Any] = []
    clause, extra = _filters(vuln_name, source_file)
    sql += clause
    params.extend(extra)
    sql += (
        " AND i.id IN ("
        "SELECT rowid FROM v_image_evidence_fts "
        "WHERE v_image_evidence_fts MATCH ?)"
    )
    params.append(fts_query)
    sql += " ORDER BY i.id LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _fetch_like(
    conn: sqlite3.Connection,
    keywords: list[str],
    vuln_name: str | None,
    limit: int,
    source_file: str | None = None,
) -> list[tuple]:
    """LIKE candidates for keywords shorter than the trigram minimum."""
    sql = _SELECT_COLUMNS
    params: list[Any] = []
    clause, extra = _filters(vuln_name, source_file)
    sql += clause
    params.extend(extra)
    conditions = " OR ".join(
        "i.ocr_text LIKE ? ESCAPE '\\'" for _ in keywords
    )
    sql += f" AND ({conditions})"
    params.extend(escape_like_literal(keyword) for keyword in keywords)
    sql += " ORDER BY i.id LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _count_matches(
    conn: sqlite3.Connection,
    fts_query: str,
    like_keywords: list[str],
    vuln_name: str | None,
    source_file: str | None = None,
) -> int:
    """Count distinct rows matching the combined FTS/LIKE conditions."""
    sql = (
        "SELECT COUNT(*) FROM v_image_evidence i "
        "WHERE i.status = 'active'"
    )
    params: list[Any] = []
    clause, extra = _filters(vuln_name, source_file)
    sql += clause
    params.extend(extra)
    conditions: list[str] = []
    if fts_query:
        conditions.append(
            "i.id IN ("
            "SELECT rowid FROM v_image_evidence_fts "
            "WHERE v_image_evidence_fts MATCH ?)"
        )
        params.append(fts_query)
    if like_keywords:
        like_condition = " OR ".join(
            "i.ocr_text LIKE ? ESCAPE '\\'" for _ in like_keywords
        )
        conditions.append(f"({like_condition})")
        params.extend(escape_like_literal(keyword) for keyword in like_keywords)
    sql += " AND (" + " OR ".join(conditions) + ")"
    return int(conn.execute(sql, params).fetchone()[0])


def _items(rows: list[tuple]) -> list[dict[str, Any]]:
    """Convert rows into response items with OCR truncation."""
    items: list[dict[str, Any]] = []
    for row in rows:
        ocr_text = row[6] or ""
        truncated = len(ocr_text) > MAX_OCR_CHARS
        items.append(
            {
                "id": row[0],
                "source_file": row[1],
                "source_page": row[2],
                "image_index": row[3],
                "image_path": row[4],
                "image_type": row[5],
                "ocr_text": ocr_text[:MAX_OCR_CHARS],
                "ocr_text_truncated": truncated,
                "ocr_confidence": row[7],
                "linked_vuln_name": row[8],
                "updated_at": row[9],
            }
        )
    return items


def search_image_evidence_payload(
    vuln_name: str | None = None,
    keywords: list[str] | None = None,
    limit: int = 10,
    source_file: str | None = None,
) -> str:
    """Search image OCR text for vulnerability evidence.

    ``vuln_name`` and ``source_file`` are applied in SQL before ``LIMIT``.
    ``source_file`` is a report-path fragment (team name, system name, or a
    slice of the path) used when the question names a specific report; without
    it the same vulnerability's screenshots from other reports can fill the
    top ``limit`` rows and hide the one being asked about.
    Keywords with at least three characters use FTS5; shorter keywords
    (notably two-character Chinese words) use a LIKE scan over ``ocr_text``
    and are merged with the FTS results. ``limit`` defaults to 10 and is
    capped at 10; one extra row is fetched to report ``total_matched`` /
    ``truncated``.
    """
    keywords = [keyword for keyword in (keywords or []) if keyword]
    capped_limit = max(1, min(int(limit or 10), MAX_LIMIT))
    if not keywords:
        return json.dumps(
            {
                "hit": False,
                "count": 0,
                "total_matched": 0,
                "truncated": False,
            },
            ensure_ascii=False,
        )

    fts_keywords = [
        keyword for keyword in keywords if len(keyword) >= MIN_FTS_CHARS
    ]
    like_keywords = [
        keyword for keyword in keywords if len(keyword) < MIN_FTS_CHARS
    ]
    fts_query = build_fts_query(fts_keywords) if fts_keywords else ""
    like_query = " OR ".join(like_keywords)
    query_parts = []
    if fts_query:
        query_parts.append(fts_query)
    if like_query:
        query_parts.append(f"LIKE:{like_query}")
    query_used = " | ".join(query_parts)

    try:
        conn = sqlite3.connect(_connection_uri(_db_path()), uri=True, timeout=5)
    except sqlite3.Error as exc:
        return json.dumps(
            {
                "hit": False,
                "count": 0,
                "total_matched": 0,
                "truncated": False,
                "error": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        try:
            total_matched = _count_matches(
                conn, fts_query, like_keywords, vuln_name, source_file
            )
            fetch_limit = capped_limit + 1
            rows: list[tuple] = []
            if fts_query:
                rows.extend(
                    _fetch_fts(conn, fts_query, vuln_name, fetch_limit, source_file)
                )
            if like_keywords:
                rows.extend(
                    _fetch_like(conn, like_keywords, vuln_name, fetch_limit, source_file)
                )
        except sqlite3.Error as exc:
            return json.dumps(
                {
                    "hit": False,
                    "count": 0,
                    "total_matched": 0,
                    "truncated": False,
                    "error": str(exc),
                    "query_used": query_used,
                },
                ensure_ascii=False,
            )

        deduped: dict[int, tuple] = {row[0]: row for row in rows}
        ordered_rows = [deduped[row_id] for row_id in sorted(deduped)]
        items_rows = ordered_rows[:capped_limit]
        truncated = total_matched > capped_limit
        if not items_rows:
            return json.dumps(
                {
                    "hit": False,
                    "count": 0,
                    "total_matched": total_matched,
                    "truncated": False,
                    "query_used": query_used,
                },
                ensure_ascii=False,
            )
        payload: dict[str, Any] = {
            "hit": True,
            "count": len(items_rows),
            "total_matched": total_matched,
            "truncated": truncated,
        }
        if truncated:
            payload["hint"] = "还有更多图片证据未返回，可调大 limit 再查"
        payload["items"] = _items(items_rows)
        payload["query_used"] = query_used
        return json.dumps(payload, ensure_ascii=False)
    finally:
        conn.close()


search_image_evidence = function_tool(
    search_image_evidence_payload, name_override="search_image_evidence"
)
