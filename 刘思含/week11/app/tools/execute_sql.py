"""Read-only SQL validation and execution tool.

注意：CTE 名可以覆盖真实表名。validate_readonly_sql 只保证引用的标识符在
白名单内，不保证语义正确。例如：
    WITH v_report AS (SELECT * FROM v_vulnerability) SELECT * FROM v_report
这条 SQL 通过校验（v_report 在白名单），但 FROM v_report 实际引用的是 CTE，
不是真实表。Agent 生成这类 SQL 时，结果可能与预期不符。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable

from agents import function_tool

ALLOWED_TABLES = {
    "v_report",
    "v_vulnerability",
    "v_type_catalog",
    "kb_entry",
    "v_image_evidence",
    "v_retest_result",
}
FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REPLACE",
}
CLAUSE_KEYWORDS = {
    "WHERE",
    "GROUP",
    "ORDER",
    "LIMIT",
    "HAVING",
    "UNION",
    "EXCEPT",
    "INTERSECT",
    "JOIN",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "CROSS",
    "NATURAL",
    "ON",
    "USING",
    "INDEXED",
    "NOT",
    "AS",
    "FROM",
}
MAX_ROWS = 1000
QUERY_TIMEOUT_SECONDS = 5.0


class ForbiddenSQLError(ValueError):
    """Raised when a SQL statement violates the read-only policy."""


def _tokenize(sql: str) -> list[tuple[str, str]]:
    """Tokenize SQL, dropping comments but preserving string literals."""
    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            end = sql.find("\n", index + 2)
            index = length if end < 0 else end + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            buffer: list[str] = []
            while index < length:
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        buffer.append(quote)
                        index += 2
                        continue
                    index += 1
                    break
                buffer.append(sql[index])
                index += 1
            kind = "string" if quote == "'" else "identifier"
            tokens.append((kind, "".join(buffer)))
            continue
        if char == "[":
            index += 1
            buffer = []
            while index < length:
                if sql[index] == "]":
                    if index + 1 < length and sql[index + 1] == "]":
                        buffer.append("]")
                        index += 2
                        continue
                    index += 1
                    break
                buffer.append(sql[index])
                index += 1
            tokens.append(("identifier", "".join(buffer)))
            continue
        if char.isalpha() or char in "_$":
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] in "_$"):
                end += 1
            tokens.append(("word", sql[index:end]))
            index = end
            continue
        if char.isdigit():
            end = index + 1
            while end < length and (sql[end].isdigit() or sql[end] == "."):
                end += 1
            tokens.append(("number", sql[index:end]))
            index = end
            continue
        tokens.append(("punct", char))
        index += 1
    return tokens


def _skip_balanced(tokens: list[tuple[str, str]], index: int) -> int:
    """Return the index after the matching ')'."""
    depth = 0
    while index < len(tokens):
        kind, value = tokens[index]
        if kind == "punct" and value == "(":
            depth += 1
        elif kind == "punct" and value == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _cte_names(tokens: list[tuple[str, str]]) -> set[str]:
    """Collect CTE names declared after WITH."""
    names: set[str] = set()
    for index, (kind, value) in enumerate(tokens):
        if kind not in ("word", "identifier"):
            continue
        cursor = index + 1
        if cursor < len(tokens) and tokens[cursor] == ("punct", "("):
            cursor = _skip_balanced(tokens, cursor)
        if (
            cursor + 1 < len(tokens)
            and tokens[cursor][0] == "word"
            and tokens[cursor][1].upper() == "AS"
            and tokens[cursor + 1] == ("punct", "(")
        ):
            names.add(value.lower())
    return names


def _read_ref(tokens: list[tuple[str, str]], index: int) -> tuple[str | None, int]:
    """Read one table reference and optional alias."""
    if index >= len(tokens):
        return None, index
    kind, value = tokens[index]
    if kind not in ("word", "identifier", "string"):
        return None, index
    parts = [value]
    cursor = index + 1
    while (
        cursor + 1 < len(tokens)
        and tokens[cursor] == ("punct", ".")
        and tokens[cursor + 1][0] in ("word", "identifier")
    ):
        parts.append(tokens[cursor + 1][1])
        cursor += 2
    table = parts[-1].lower()

    if cursor < len(tokens):
        kind, value = tokens[cursor]
        if kind == "word" and value.upper() == "AS":
            cursor += 1
            if cursor < len(tokens) and tokens[cursor][0] in (
                "word",
                "identifier",
            ):
                cursor += 1
        elif kind in ("word", "identifier") and value.upper() not in CLAUSE_KEYWORDS:
            cursor += 1
    return table, cursor


def _table_references(tokens: list[tuple[str, str]]) -> set[str]:
    """Extract table references after every FROM/JOIN, including subqueries."""
    tables: set[str] = set()
    index = 0
    while index < len(tokens):
        kind, value = tokens[index]
        if kind != "word" or value.upper() not in ("FROM", "JOIN"):
            index += 1
            continue
        cursor = index + 1
        while cursor < len(tokens):
            if tokens[cursor] == ("punct", "("):
                break
            table, cursor = _read_ref(tokens, cursor)
            if table is None:
                break
            tables.add(table)
            if cursor < len(tokens) and tokens[cursor] == ("punct", ","):
                cursor += 1
                continue
            break
        index = cursor
    return tables


def validate_readonly_sql(sql: str) -> bool:
    """Validate that *sql* is a single read-only SELECT over allowed tables."""
    tokens = _tokenize(sql)
    if not tokens:
        raise ForbiddenSQLError("SQL is empty or contains only comments")

    first_kind, first_value = tokens[0]
    if first_kind != "word" or first_value.upper() not in ("SELECT", "WITH"):
        raise ForbiddenSQLError("SQL must start with SELECT or WITH")

    semicolons = [
        index for index, token in enumerate(tokens) if token == ("punct", ";")
    ]
    if len(semicolons) > 1 or (semicolons and semicolons[0] != len(tokens) - 1):
        raise ForbiddenSQLError("multiple statements are not allowed")
    if semicolons:
        tokens = tokens[:-1]

    for kind, value in tokens:
        if kind == "word" and value.upper() in FORBIDDEN_KEYWORDS:
            raise ForbiddenSQLError(f"forbidden keyword: {value.upper()}")

    ctes = _cte_names(tokens)
    for table in _table_references(tokens):
        if table not in ALLOWED_TABLES and table not in ctes:
            raise ForbiddenSQLError(f"table not allowed: {table}")
    return True


def _db_path() -> Path:
    """Return the database path from VULN_DB_PATH."""
    return Path(os.environ.get("VULN_DB_PATH", "app/db/vuln.db"))


def _connection_uri(db_path: Path) -> str:
    """Build the read-only SQLite URI."""
    return f"{db_path.resolve().as_uri()}?mode=ro"


def _progress_handler(deadline: float) -> Callable[[], int]:
    """Return a progress handler that interrupts after the deadline."""

    def handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    return handler


def _error(sql: str, message: str) -> str:
    """Serialize an error response."""
    return json.dumps({"ok": False, "error": message, "sql": sql}, ensure_ascii=False)


def execute_sql_query(sql: str) -> str:
    """Execute a validated read-only SQL statement and return JSON text."""
    try:
        validate_readonly_sql(sql)
    except ForbiddenSQLError as exc:
        return _error(sql, str(exc))

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            _connection_uri(_db_path()), uri=True, timeout=QUERY_TIMEOUT_SECONDS
        )
        connection.set_progress_handler(
            _progress_handler(time.monotonic() + QUERY_TIMEOUT_SECONDS), 1000
        )
        cursor = connection.execute(sql)
        columns = [description[0] for description in cursor.description or []]
        fetched = cursor.fetchmany(MAX_ROWS + 1)
        truncated = len(fetched) > MAX_ROWS
        rows = [list(row) for row in fetched[:MAX_ROWS]]
        payload = {
            "ok": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "sql": sql,
        }
        if truncated:
            payload["truncated"] = True
        return json.dumps(payload, ensure_ascii=False, default=str)
    except sqlite3.Error as exc:
        return _error(sql, str(exc))
    finally:
        if connection is not None:
            connection.close()


execute_sql = function_tool(execute_sql_query, name_override="execute_sql")
