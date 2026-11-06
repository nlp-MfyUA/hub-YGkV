"""
阶段 1：数据库解析。

    1. 用原生 sqlite3 替代 SQLAlchemy —— 
       `engine.execute()`，在 SQLAlchemy 2.x 里已被移除，跑不起来；
    2. 以只读方式打开数据库（`mode=ro` + `PRAGMA query_only`），从连接层面杜绝写操作；
    3. 执行 SQL 时加行数上限和超时中断（progress handler），防止大表全表扫描拖死进程；
    4. 额外提供 get_catalog_text / get_schema_text，把解析结果整理成提示词可直接用的文本。

解析内容：
    表清单、每张表的字段（类型 / 主键 / 非空 / 默认值）、
    字段统计（唯一值个数、空值个数、最大最小、众数、样例值）、
    表间外键关系、每张表的样例行。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

# sqlite 的系统表不参与业务问答
SYSTEM_TABLE_PREFIX = "sqlite_"


def _quote(identifier: str) -> str:
    """安全地引用一个标识符（表名 / 字段名）。"""
    return '"' + identifier.replace('"', '""') + '"'


def _is_text_type(col_type: str) -> bool:
    upper = (col_type or "").upper()
    return any(key in upper for key in ("CHAR", "TEXT", "CLOB"))


def _fmt(value: Any, limit: int = 50) -> str:
    """把字段值格式化成提示词里能看的短字符串。"""
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return f"<blob {len(value)} bytes>"
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


class DBParser:
    """解析 sqlite 数据库结构，并提供只读的 SQL 校验 / 执行能力。"""

    def __init__(self, db_path: str | Path, sample_limit: int = 3) -> None:
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(f"数据库不存在：{self.db_path}")

        self.sample_limit = sample_limit
        # LangChain 的同步工具可能在不同线程里执行，连接必须允许跨线程；
        # 同时用一把锁串行化查询，避免同一连接被并发使用。
        self._lock = threading.RLock()
        # 只读打开：即使生成的 SQL 里混进了写操作，sqlite 也会直接拒绝
        self.conn = sqlite3.connect(
            f"file:{self.db_path.as_posix()}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only = ON")

        self.table_names: list[str] = []
        self._table_fields: dict[str, dict[str, dict]] = {}
        self._table_sample: dict[str, dict[str, Any]] = {}
        self._row_counts: dict[str, int] = {}
        self.foreign_keys: list[dict] = []

        self._parse()

    # ------------------------------------------------------------------ #
    # 解析
    # ------------------------------------------------------------------ #
    def _parse(self) -> None:
        self.table_names = [
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if not row[0].startswith(SYSTEM_TABLE_PREFIX)
        ]

        for table in self.table_names:
            self._row_counts[table] = self.conn.execute(
                f"SELECT COUNT(*) FROM {_quote(table)}"
            ).fetchone()[0]

            # 外键
            for fk in self.conn.execute(f"PRAGMA foreign_key_list({_quote(table)})"):
                self.foreign_keys.append(
                    {
                        "constrained_table": table,
                        "constrained_columns": [fk["from"]],
                        "referred_table": fk["table"],
                        "referred_columns": [fk["to"]],
                    }
                )

            # 字段信息 + 字段统计
            self._table_fields[table] = {}
            for col in self.conn.execute(f"PRAGMA table_info({_quote(table)})"):
                name = col["name"]
                col_type = col["type"] or "TEXT"
                self._table_fields[table][name] = {
                    "name": name,
                    "type": col_type,
                    "notnull": bool(col["notnull"]),
                    "pk": bool(col["pk"]),
                    "default": col["dflt_value"],
                    **self._column_stats(table, name, col_type),
                }

            # 样例行（第一行）
            row = self.conn.execute(f"SELECT * FROM {_quote(table)} LIMIT 1").fetchone()
            self._table_sample[table] = dict(row) if row else {}

    def _column_stats(self, table: str, column: str, col_type: str) -> dict:
        """统计单个字段：唯一值 / 空值 / 最大最小 / 众数 / 样例值。"""
        col = _quote(column)
        table_q = _quote(table)

        row = self.conn.execute(
            f"SELECT COUNT(*) AS n, COUNT(DISTINCT {col}) AS d, "
            f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS nulls, "
            f"MIN({col}) AS min_v, MAX({col}) AS max_v "
            f"FROM {table_q}"
        ).fetchone()

        stats: dict[str, Any] = {
            "distinct": row["d"],
            "nulls": row["nulls"] or 0,
            "min": _fmt(row["min_v"]),
            "max": _fmt(row["max_v"]),
            "mode": None,
            "samples": [],
        }

        # 众数：只对文本类字段有意义（数值字段的众数噪声大）
        if _is_text_type(col_type):
            mode = self.conn.execute(
                f"SELECT {col} AS v, COUNT(*) AS c FROM {table_q} "
                f"WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY c DESC LIMIT 1"
            ).fetchone()
            stats["mode"] = _fmt(mode["v"]) if mode else None

        # 样例值：最多取 sample_limit 个不同的非空值
        samples = self.conn.execute(
            f"SELECT DISTINCT {col} FROM {table_q} WHERE {col} IS NOT NULL LIMIT {self.sample_limit}"
        ).fetchall()
        stats["samples"] = [_fmt(s[0]) for s in samples]

        return stats

    # ------------------------------------------------------------------ #
    # 查询接口（给工作流 / 提示词使用）
    # ------------------------------------------------------------------ #
    def get_table_fields(self, table_name: str) -> dict[str, dict]:
        """返回某张表的字段信息（名字 -> 元信息）。"""
        self._check_table(table_name)
        return self._table_fields[table_name]

    def get_data_relations(self, table_names: Iterable[str] | None = None) -> list[dict]:
        """返回外键关系；传 table_names 时只返回涉及这些表的关系。"""
        if table_names is None:
            return list(self.foreign_keys)
        selected = set(table_names)
        return [
            fk
            for fk in self.foreign_keys
            if fk["constrained_table"] in selected and fk["referred_table"] in selected
        ]

    @property
    def row_counts(self) -> dict[str, int]:
        """每张表的行数（只读副本）。"""
        return dict(self._row_counts)

    def get_table_sample(self, table_name: str) -> dict[str, Any]:
        """返回某张表的第一行数据。"""
        self._check_table(table_name)
        return self._table_sample[table_name]

    def get_catalog_text(self) -> str:
        """给「表选择」阶段用的紧凑表目录。"""
        lines: list[str] = []
        for table in self.table_names:
            fields = self._table_fields[table]
            cols = []
            for meta in fields.values():
                flag = " PK" if meta["pk"] else ""
                cols.append(f"{meta['name']} {meta['type']}{flag}")
            sample = ", ".join(f"{k}={_fmt(v, 30)}" for k, v in self._table_sample[table].items())
            lines.append(f"### {table}（{self._row_counts[table]} 行）")
            lines.append("字段：" + ", ".join(cols))
            lines.append("样例：" + (sample or "（空表）"))
            lines.append("")
        return "\n".join(lines).strip()

    def get_schema_text(self, table_names: Iterable[str]) -> str:
        """给「SQL 生成 / 改写」阶段用的完整表结构（含字段统计）。"""
        blocks: list[str] = []
        for table in table_names:
            self._check_table(table)
            lines = [f"### 表 {table}（{self._row_counts[table]} 行）", "字段："]
            for meta in self._table_fields[table].values():
                flags = []
                if meta["pk"]:
                    flags.append("主键")
                if meta["notnull"]:
                    flags.append("非空")
                if meta["default"] is not None:
                    flags.append(f"默认值 {meta['default']}")
                flag_text = f"（{'，'.join(flags)}）" if flags else ""

                stats = [f"唯一值 {meta['distinct']}", f"空值 {meta['nulls']}"]
                # 文本字段的 max/min 是按字典序算的，对理解数据没有意义，不展示
                if not _is_text_type(meta["type"]) and (meta["min"] != "NULL" or meta["max"] != "NULL"):
                    stats.append(f"范围 {meta['min']} ~ {meta['max']}")
                if meta["mode"]:
                    stats.append(f"众数 {meta['mode']}")
                if meta["samples"]:
                    stats.append(f"样例 {meta['samples']}")

                lines.append(f"- {meta['name']} {meta['type']}{flag_text}：{'; '.join(stats)}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def get_relations_text(self, table_names: Iterable[str] | None = None) -> str:
        relations = self.get_data_relations(table_names)
        if not relations:
            return "（无外键关系）"
        return "\n".join(
            f"- {fk['constrained_table']}.{fk['constrained_columns'][0]} "
            f"-> {fk['referred_table']}.{fk['referred_columns'][0]}"
            for fk in relations
        )

    def get_samples_text(self, table_names: Iterable[str]) -> str:
        lines = []
        for table in table_names:
            sample = self.get_table_sample(table)
            if sample:
                lines.append(f"### {table}\n" + ", ".join(f"{k}={_fmt(v, 30)}" for k, v in sample.items()))
        return "\n\n".join(lines) or "（无样例数据）"

    # ------------------------------------------------------------------ #
    # 校验 / 执行
    # ------------------------------------------------------------------ #
    def check_sql(self, sql: str) -> tuple[bool, str]:
        """用 EXPLAIN 让 sqlite 编译一遍 SQL（不真正执行），语法 / 表名 / 字段名错误都会暴露。"""
        try:
            with self._lock:
                self.conn.execute("EXPLAIN " + sql).fetchall()
            return True, "ok"
        except sqlite3.Error as exc:
            return False, str(exc)

    def execute_sql(
        self,
        sql: str,
        max_rows: int = 200,
        timeout_s: float = 10.0,
    ) -> tuple[list[str], list[dict[str, Any]], bool]:
        """执行查询，返回 (列名, 行数据, 是否被截断)。

        用 sqlite 的 progress handler 做超时中断：每 1 万个 VM 指令检查一次，
        超时就让 sqlite 抛 interrupted，避免一条全表扫描把工作流卡死。
        """
        deadline = time.monotonic() + timeout_s

        def _abort_if_timeout() -> int:
            return 1 if time.monotonic() > deadline else 0

        with self._lock:
            self.conn.set_progress_handler(_abort_if_timeout, 10_000)
            try:
                cursor = self.conn.execute(sql)
                columns = [d[0] for d in cursor.description or []]
                rows = [dict(r) for r in cursor.fetchmany(max_rows + 1)]
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    raise TimeoutError(f"SQL 执行超时（>{timeout_s}s）") from exc
                raise
            finally:
                self.conn.set_progress_handler(None, 10_000)

        truncated = len(rows) > max_rows
        return columns, rows[:max_rows], truncated

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DBParser":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _check_table(self, table_name: str) -> None:
        if table_name not in self._table_fields:
            raise KeyError(f"数据库中不存在表：{table_name}")
