"""Schema introspection tool for the ChatBI agent."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from agents import function_tool

ALLOWED_TABLES = (
    "v_report",
    "v_vulnerability",
    "v_type_catalog",
    "kb_entry",
    "v_image_evidence",
    "v_retest_result",
)

ENUM_VALUES: dict[str, dict[str, list[str]]] = {
    "v_vulnerability": {
        "severity": ["高危", "中危", "低危", "信息"],
        "extraction_method": ["table_row", "kv_block", "text_block"],
        "status": ["active", "superseded", "orphaned"],
    },
    "v_retest_result": {
        "retest_status": [
            "fixed",
            "unfixed",
            "partial",
            "not_reproducible",
            "unknown",
        ],
        "match_confidence": ["exact", "fuzzy", "none"],
        "status": ["active", "superseded", "orphaned"],
    },
    "v_image_evidence": {
        "image_type": ["screenshot", "chart", "unknown"],
        "ocr_confidence": ["high", "medium", "low"],
        "status": ["active", "superseded", "orphaned"],
    },
    "v_report": {
        "report_type": ["pentest", "retest"],
        "status": ["active", "orphaned"],
    },
    "kb_entry": {
        "status": ["pending", "approved", "rejected"],
    },
    "v_type_catalog": {},
}

COLUMN_COMMENTS = {
    "v_report": {
        "report_name": "报告相对路径（deliverables/ 下的 relative_path）",
        "report_type": "pentest=渗透报告，retest=回归报告",
        "parent_report_id": "retest 对应的渗透报告 id",
    },
    "v_vulnerability": {
        "source_file": "来源报告相对路径",
        "vuln_name": "漏洞名称",
        "severity": "归一化风险等级",
        "severity_raw": "报告原文的风险等级",
        "instance_index": "同 (vuln_name, component) 在报告内的第几条",
        "description_snippet": "漏洞描述片段，<=303 字符",
        "extraction_method": "提取方式",
    },
    "v_retest_result": {
        "vuln_id": "匹配到的渗透漏洞 id；未匹配为 NULL",
        "raw_vuln_name": "回归报告原文漏洞名",
        "instance_index": "同 (raw_vuln_name, component) 在回归报告内的第几条",
        "retest_status": "归一化复测状态",
        "evidence_page": "复测状态所在页",
        "match_confidence": "exact=精确匹配，none=未匹配",
    },
    "v_image_evidence": {
        "image_path": "相对图片根目录的路径（由 image_loader 生成）",
        "linked_vuln_name": "关联漏洞名（启发式，未关联为 NULL）",
        "generated_description": "MVP 恒为 NULL",
    },
    "v_type_catalog": {
        "type_code": "类型编码",
        "type_name": "类型中文名",
    },
    "kb_entry": {
        "question_pattern": "问题模式",
        "sql_template": "参数化 SQL 模板",
    },
}

_SCHEMA_CACHE: dict[str, str] = {}


def _db_path() -> Path:
    """Return the database path from VULN_DB_PATH."""
    return Path(os.environ.get("VULN_DB_PATH", "app/db/vuln.db"))


def _connection_uri(db_path: Path) -> str:
    """Build the read-only SQLite URI."""
    return f"{db_path.resolve().as_uri()}?mode=ro"


def _split_columns(create_sql: str) -> list[str]:
    """Split the body of a CREATE TABLE statement into column definitions."""
    start = create_sql.find("(")
    end = create_sql.rfind(")")
    if start < 0 or end <= start:
        return []
    body = create_sql[start + 1 : end]
    columns: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            columns.append("".join(buffer).strip())
            buffer = []
            continue
        buffer.append(char)
    if buffer:
        columns.append("".join(buffer).strip())
    return columns


def _parse_columns(create_sql: str) -> list[dict[str, Any]]:
    """Parse column names and types from a CREATE TABLE statement."""
    parsed: list[dict[str, Any]] = []
    for definition in _split_columns(create_sql):
        upper = definition.upper()
        if upper.startswith(
            ("PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN KEY", "CONSTRAINT")
        ):
            continue
        match = re.match(
            r'^["`\[]?(?P<name>[A-Za-z_][\w]*)["`\]]?\s+(?P<type>[^,\s]+)', definition
        )
        if not match:
            continue
        parsed.append(
            {
                "name": match.group("name"),
                "type": match.group("type").upper(),
                "nullable": "NOT NULL" not in upper,
            }
        )
    return parsed


def _read_cte_tables(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read table/column definitions for the whitelisted tables."""
    tables: dict[str, Any] = {}
    for table in ALLOWED_TABLES:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        columns = _parse_columns(row[0]) if row and row[0] else []
        enums = ENUM_VALUES.get(table, {})
        comments = COLUMN_COMMENTS.get(table, {})
        for column in columns:
            enum = enums.get(column["name"])
            if enum:
                column["enum"] = enum
            comment = comments.get(column["name"])
            if comment:
                column["comment"] = comment
        tables[table] = {"columns": columns}
    return tables


def _read_type_catalog(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """Read all rows from v_type_catalog."""
    return [
        {"type_code": code, "type_name": name}
        for code, name in conn.execute(
            "SELECT type_code, type_name FROM v_type_catalog ORDER BY type_code"
        )
    ]


def get_schema_payload() -> str:
    """Build the schema payload, caching it for the process lifetime."""
    if _SCHEMA_CACHE:
        return _SCHEMA_CACHE["data"]
    conn = sqlite3.connect(_connection_uri(_db_path()), uri=True, timeout=5)
    try:
        payload = {
            "tables": _read_cte_tables(conn),
            "type_catalog": _read_type_catalog(conn),
        }
    finally:
        conn.close()
    rendered = json.dumps(payload, ensure_ascii=False)
    _SCHEMA_CACHE["data"] = rendered
    return rendered


def reset_schema_cache() -> None:
    """Clear the in-process schema cache (for tests)."""
    _SCHEMA_CACHE.clear()


get_schema = function_tool(get_schema_payload, name_override="get_schema")
