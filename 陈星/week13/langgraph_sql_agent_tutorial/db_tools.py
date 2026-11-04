"""第 1 层：纯 Python + SQLite。这里不调用大模型。

安全边界：只读连接、只允许 SELECT/只读 WITH、EXPLAIN 校验、超时和结果条数限制。
这是供学习的 SQLite 防护示例，不等于任意数据库的生产安全网关。
"""

from __future__ import annotations

import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

MAX_ROWS = 200
MAX_CELL_CHARS = 1000
QUERY_TIMEOUT = 5.0

# 去掉字符串/标识符/注释，再扫描关键字，避免把 'DELETE' 字符串误认为写操作。
MASK_PATTERN = re.compile(
    r"""'(?:''|[^'])*'|"(?:\"\"|[^"])*"|`(?:``|[^`])*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/""",
    re.DOTALL,
)
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|PRAGMA|ATTACH|DETACH|"
    r"VACUUM|REINDEX|TRIGGER|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b",
    re.IGNORECASE,
)


def quote_identifier(name: str) -> str:
    """只给数据库元数据返回的表名加引号，不拼接用户输入。"""
    return '"' + name.replace('"', '""') + '"'


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[str]]
    truncated: bool

    @property
    def shown_rows(self) -> int:
        """只表示本次取出的行数，并非全表的实际总行数。"""
        return len(self.rows)


class SQLiteTools:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(f"找不到数据库: {self.db_path}")
        self.catalog = self._load_catalog()

    @contextmanager
    def connect(self):
        # mode=ro 阻止文件写入；query_only 进一步限制写事务。
        con = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
        try:
            con.execute("PRAGMA query_only = ON")
            yield con
        finally:
            con.close()

    def _load_catalog(self) -> dict[str, dict]:
        """读取表、字段、外键；缓存一次供多个问题重复使用。"""
        catalog = {}
        with self.connect() as con:
            names = [
                row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            for table in names:
                q = quote_identifier(table)
                cols = [
                    f"{r[1]} {r[2]}{' PRIMARY KEY' if r[5] else ''}"
                    for r in con.execute(f"PRAGMA table_info({q})")
                ]
                fks = [
                    f"{table}.{r[3]} -> {r[2]}.{r[4]}"
                    for r in con.execute(f"PRAGMA foreign_key_list({q})")
                ]
                catalog[table] = {"columns": cols, "foreign_keys": fks}
        return catalog

    def catalog_text(self) -> str:
        """第一位 Agent 看到全库的轻量说明。"""
        return self.schema_text(list(self.catalog))

    def schema_text(self, tables: list[str]) -> str:
        """第二、第三位 Agent 只看到所选表的具体结构。"""
        chunks = []
        for table in tables:
            if table not in self.catalog:
                raise ValueError(f"未知表: {table}")
            info = self.catalog[table]
            chunks.append(
                f"表 {table}\n"
                + "  列: " + ", ".join(info["columns"]) + "\n"
                + "  外键: " + (", ".join(info["foreign_keys"]) or "无")
            )
        return "\n\n".join(chunks)

    def validate(self, raw_sql: str) -> str:
        """安全检查 + SQLite EXPLAIN 编译，不执行真实查询。"""
        sql = raw_sql.strip()
        if sql.startswith("```"):
            sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.I).strip()
        if sql.endswith(";"):
            sql = sql[:-1].rstrip()
        masked = MASK_PATTERN.sub(" ", sql)
        if not re.match(r"^\s*(SELECT|WITH)\b", masked, flags=re.I):
            raise ValueError("只允许 SELECT 或只读 WITH 查询")
        if ";" in masked:
            raise ValueError("禁止多条 SQL 语句")
        if FORBIDDEN.search(masked):
            raise ValueError("检测到禁止的写入或管理语句")
        with self.connect() as con:
            con.execute("EXPLAIN " + sql).fetchone()
        return sql

    def execute(self, checked_sql: str) -> QueryResult:
        """只执行已经通过 validate() 的 SQL。"""
        with self.connect() as con:
            deadline = time.monotonic() + QUERY_TIMEOUT
            con.set_progress_handler(
                lambda: int(time.monotonic() >= deadline), 1000
            )
            cursor = con.execute(checked_sql)
            columns = [c[0] for c in (cursor.description or [])]
            fetched = cursor.fetchmany(MAX_ROWS + 1)
            truncated = len(fetched) > MAX_ROWS
            rows = [
                [
                    ("" if value is None else str(value))[:MAX_CELL_CHARS]
                    for value in record
                ]
                for record in fetched[:MAX_ROWS]
            ]
            return QueryResult(columns=columns, rows=rows, truncated=truncated)
