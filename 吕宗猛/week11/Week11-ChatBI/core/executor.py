"""只读 SQL 执行与事实校验。

安全策略（不依赖模型自律）：
1. 以 URI `mode=ro&immutable=1` 打开，物理上不可写；
2. 安装 authorizer，拒绝 INSERT/UPDATE/DELETE/DDL/ATTACH/PRAGMA 等动作；
3. 通过 `EXPLAIN` 让 SQLite 自身完成语法与表名字段名校验（不执行数据）；
4. 执行阶段挂 progress_handler，超时即中断；
5. 结果集按行数上限截断。
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import config
from core import schema as schema_mod

_DENIED_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_PRAGMA,
}


class QueryTimeout(RuntimeError):
    """查询执行超过时间上限。"""


@dataclass
class ValidationResult:
    ok: bool
    error: str | None = None
    plan: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    elapsed_ms: float
    sql: str


def _authorizer(action: int, *_args) -> int:
    return sqlite3.SQLITE_DENY if action in _DENIED_ACTIONS else sqlite3.SQLITE_OK


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH).resolve()
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True, timeout=3.0, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    con.set_authorizer(_authorizer)
    return con


def _jsonable(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


# ---------------------------------------------------------------- 校验


def explain_validate(sql: str, db_path: Path | str | None = None) -> ValidationResult:
    """用 SQLite 自身验证语法/表名/字段名，不读取任何业务数据。"""
    started = time.perf_counter()
    con = None
    try:
        con = connect(db_path)
        # EXPLAIN 会完整编译语句，未知表名/字段名会在此报错
        con.execute(f"EXPLAIN {sql}").fetchall()
        plan_rows = con.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        plan = [" | ".join(str(part) for part in row[3:]) for row in plan_rows]
        return ValidationResult(
            ok=True,
            error=None,
            plan=plan,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except sqlite3.Error as exc:
        message = str(exc)
        if "not authorized" in message.lower():
            message = f"SQLite 拒绝执行该语句（只读策略）：{message}"
        return ValidationResult(
            ok=False,
            error=message,
            plan=[],
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as exc:  # noqa: BLE001 - 兜底，保证评审不因异常中断
        return ValidationResult(
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            plan=[],
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    finally:
        if con is not None:
            con.close()


# ---------------------------------------------------------------- 执行


def run_query(
    sql: str,
    max_rows: int | None = None,
    timeout: float | None = None,
    db_path: Path | str | None = None,
) -> QueryResult:
    max_rows = max_rows or config.MAX_RESULT_ROWS
    timeout = config.QUERY_TIMEOUT_SECONDS if timeout is None else timeout
    deadline = time.monotonic() + timeout
    started = time.perf_counter()
    con = None
    try:
        con = connect(db_path)

        def _watchdog() -> int:
            return 1 if time.monotonic() > deadline else 0

        con.set_progress_handler(_watchdog, 5_000)
        cursor = con.execute(sql)
        columns = [item[0] for item in (cursor.description or [])]
        fetched = cursor.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [[_jsonable(value) for value in row] for row in fetched[:max_rows]]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            sql=sql,
        )
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise QueryTimeout(f"查询超过 {timeout:g} 秒被中断，请缩小范围或增加过滤条件") from exc
        raise
    finally:
        if con is not None:
            con.close()


# ---------------------------------------------------------------- Agent 工具用到的探查


def sample_values(table: str, column: str, limit: int = 10, db_path: Path | str | None = None) -> list[str]:
    info = schema_mod.get_schema()
    target = info.table(table)
    if target is None or target.column(column) is None:
        raise ValueError(f"表/字段不存在：{table}.{column}")
    limit = max(1, min(int(limit), 30))
    con = connect(db_path)
    try:
        sql = f"SELECT DISTINCT {_q(column)} FROM {_q(table)} WHERE {_q(column)} IS NOT NULL LIMIT ?"
        return [str(row[0]) for row in con.execute(sql, (limit,))]
    finally:
        con.close()


def search_text(
    keyword: str,
    limit: int = 6,
    db_path: Path | str | None = None,
) -> list[dict]:
    """在文本类字段中模糊查找关键字，帮助确认用户提到的实体在库中的写法。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    info = schema_mod.get_schema()
    limit = max(1, min(int(limit), 10))
    pattern = f"%{keyword}%"
    hits: list[dict] = []
    con = connect(db_path)
    try:
        for table_name in sorted(info.tables):
            table = info.tables[table_name]
            for col in table.columns:
                ctype = (col.type or "").upper()
                if not any(token in ctype for token in ("CHAR", "TEXT", "CLOB", "")):
                    continue
                if ctype.startswith("INT") or ctype.startswith("NUM") or ctype.startswith("REAL"):
                    continue
                try:
                    rows = con.execute(
                        f"SELECT {_q(col.name)} FROM {_q(table_name)} "
                        f"WHERE {_q(col.name)} LIKE ? LIMIT ?",
                        (pattern, limit),
                    ).fetchall()
                except sqlite3.Error:
                    continue
                if rows:
                    hits.append(
                        {
                            "table": table_name,
                            "column": col.name,
                            "examples": [str(row[0]) for row in rows],
                        }
                    )
                    if len(hits) >= limit:
                        return hits
    finally:
        con.close()
    return hits


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
