"""Stage 6 · SQL 执行。

安全与资源控制：
- 只读连接（file:...?mode=ro），物理上杜绝写操作；
- SQLite authorizer 只放行 SQLITE_READ / SQLITE_SELECT / SQLITE_FUNCTION，
  并显式拒绝 load_extension，其余动作一律 SQLITE_DENY；
- 行数上限 row_limit（超出即截断并标记 truncated）；
- 软超时：progress handler 周期性检查耗时，超时中断查询。

本模块同时提供 execute_readonly()，供评测模块执行 gold SQL 做结果比对。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ..db import connect_readonly
from ..models import STATUS_ERROR, STATUS_OK, STAGE_SQL_EXECUTE, ExecutionResult, StageTrace

# sqlite3.h 中的动作码（Python 未全部导出，这里按 C 头文件字面量定义）
SQLITE_OK = 0
SQLITE_DENY = 1
SQLITE_READ = 20        # 读某列
SQLITE_SELECT = 21      # SELECT 语句
SQLITE_FUNCTION = 31    # 调用函数

_ALLOWED_ACTIONS = {SQLITE_READ, SQLITE_SELECT, SQLITE_FUNCTION}


def _readonly_authorizer(action: int, arg1, arg2, dbname, source) -> int:
    """只读 authorizer：除读取与函数调用外一律拒绝。"""
    if action == SQLITE_FUNCTION and arg1 == "load_extension":
        return SQLITE_DENY
    return SQLITE_OK if action in _ALLOWED_ACTIONS else SQLITE_DENY


def execute_readonly(db_path: str | Path, sql: str, *,
                     row_limit: int = 100,
                     timeout_seconds: float = 10.0) -> ExecutionResult:
    """在只读 + authorizer 保护下执行单条 SELECT，返回 ExecutionResult。"""
    conn = connect_readonly(db_path)
    conn.set_authorizer(_readonly_authorizer)
    start = time.monotonic()

    def _progress() -> int:
        return 1 if (time.monotonic() - start) > timeout_seconds else 0

    conn.set_progress_handler(_progress, 10_000)
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(row_limit + 1)
        truncated = len(rows) > row_limit
        rows = rows[:row_limit]
        return ExecutionResult(
            ok=True,
            columns=columns,
            rows=[tuple(r) for r in rows],
            row_count=len(rows),
            truncated=truncated,
            duration_ms=(time.monotonic() - start) * 1000,
        )
    except sqlite3.Error as exc:
        return ExecutionResult(
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=(time.monotonic() - start) * 1000,
        )
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


class SqlExecutionStage:
    name = STAGE_SQL_EXECUTE

    def __init__(self, db_path: str | Path, *,
                 row_limit: int = 100, timeout_seconds: float = 10.0):
        self._db_path = Path(db_path)
        self._row_limit = row_limit
        self._timeout = timeout_seconds

    def run(self, sql: str, attempt: int = 1) -> tuple[ExecutionResult, StageTrace]:
        result = execute_readonly(
            self._db_path, sql,
            row_limit=self._row_limit,
            timeout_seconds=self._timeout,
        )
        if result.ok:
            brief = f"{result.row_count} 行" + ("（已截断）" if result.truncated else "")
            brief += f"｜列: {', '.join(result.columns)}"
            trace = StageTrace(
                stage=self.name, status=STATUS_OK,
                input_brief=sql, output_brief=brief,
                detail=f"只读连接 + authorizer + 行数上限 {self._row_limit} + 超时 {self._timeout}s",
                duration_ms=result.duration_ms, attempt=attempt,
            )
        else:
            trace = StageTrace(
                stage=self.name, status=STATUS_ERROR,
                input_brief=sql, output_brief="（执行失败）",
                detail=result.error, duration_ms=result.duration_ms, attempt=attempt,
            )
        return result, trace


__all__ = ["SqlExecutionStage", "execute_readonly", "STATUS_ERROR", "STATUS_OK"]
