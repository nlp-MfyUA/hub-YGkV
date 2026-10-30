"""数据库结构解析：读取 SQLite 库，产出结构化模型与可注入 Prompt 的文本。

只使用标准库 sqlite3，以只读方式打开，不修改源库。
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import config

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
INTERNAL_PREFIX = "sqlite_"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    notnull: bool
    default: str | None
    pk: int

    @property
    def is_pk(self) -> bool:
        return self.pk > 0


@dataclass(frozen=True)
class ForeignKeyInfo:
    table: str
    column: str
    ref_table: str
    ref_column: str

    def edge(self) -> str:
        return f"{self.table}.{self.column} -> {self.ref_table}.{self.ref_column}"


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKeyInfo]
    row_count: int
    indexes: list[str] = field(default_factory=list)

    def column(self, name: str) -> ColumnInfo | None:
        lowered = name.lower()
        for item in self.columns:
            if item.name.lower() == lowered:
                return item
        return None


@dataclass
class SchemaInfo:
    db_path: str
    tables: dict[str, TableInfo]
    built_at: float
    build_ms: float
    fingerprint: tuple[int, int]
    temporal: list[tuple[str, str, str, str]] = field(default_factory=list)

    def temporal_text(self) -> str:
        if not self.temporal:
            return "（未检测到日期字段）"
        return "\n".join(
            f"- {table}.{column}: {low} ~ {high}" for table, column, low, high in self.temporal
        )

    # ---------- 视图 ----------

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def column_count(self) -> int:
        return sum(len(t.columns) for t in self.tables.values())

    @property
    def foreign_key_count(self) -> int:
        return sum(len(t.foreign_keys) for t in self.tables.values())

    def table(self, name: str) -> TableInfo | None:
        if name in self.tables:
            return self.tables[name]
        lowered = name.lower()
        for key, value in self.tables.items():
            if key.lower() == lowered:
                return value
        return None

    # ---------- Prompt 文本 ----------

    def ddl(self) -> str:
        blocks: list[str] = []
        for name in sorted(self.tables):
            table = self.tables[name]
            lines = [f"CREATE TABLE {_quote(name)} ("]
            parts: list[str] = []
            for col in table.columns:
                piece = f"  {_quote(col.name)} {col.type or 'TEXT'}"
                if col.is_pk:
                    piece += " PRIMARY KEY"
                if col.notnull and not col.is_pk:
                    piece += " NOT NULL"
                parts.append(piece)
            for fk in table.foreign_keys:
                parts.append(
                    f"  FOREIGN KEY ({_quote(fk.column)}) REFERENCES "
                    f"{_quote(fk.ref_table)}({_quote(fk.ref_column)})"
                )
            lines.append(",\n".join(parts))
            lines.append(")")
            blocks.append("\n".join(lines) + f"\n-- {table.row_count} rows")
        return "\n\n".join(blocks)

    def relations(self) -> str:
        edges = [
            fk.edge()
            for name in sorted(self.tables)
            for fk in self.tables[name].foreign_keys
        ]
        return "\n".join(edges) if edges else "（无外键）"

    def table_directory(self) -> str:
        return "\n".join(
            f"- {name}（{self.tables[name].row_count} 行）" for name in sorted(self.tables)
        )

    def prompt(self) -> str:
        return (
            "### 数据库方言\n"
            "SQLite 3，只读模式。标识符大小写不敏感，但请与下方定义逐字一致。\n"
            "日期字段以 TEXT 存储，格式 'YYYY-MM-DD HH:MM:SS'（例如 invoices.InvoiceDate）。\n"
            "金额字段为 NUMERIC；SQLite 中整数相除会截断，需要比例时先乘 1.0。\n\n"
            "### 表结构\n"
            f"{self.ddl()}\n\n"
            "### 外键关系（多表查询必须沿这些边 JOIN）\n"
            f"{self.relations()}\n\n"
            "### 已知数据范围（日期字段真实取值）\n"
            f"{self.temporal_text()}\n"
            "若用户给定的时间范围落在上述范围之外，不要臆造数据，也不要擅自改动用户的时间条件；"
            "按用户条件生成查询，并在 reasoning 中说明该范围可能无数据。"
        )

    def describe(self, table_name: str) -> str:
        table = self.table(table_name)
        if table is None:
            return f"错误：不存在表 {table_name}。可用表：{', '.join(sorted(self.tables))}"
        lines = [f"表 {table.name}（{table.row_count} 行）", "字段："]
        for col in table.columns:
            flags = []
            if col.is_pk:
                flags.append("PK")
            if col.notnull:
                flags.append("NOT NULL")
            if col.default is not None:
                flags.append(f"DEFAULT {col.default}")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"- {col.name} {col.type}{suffix}")
        if table.foreign_keys:
            lines.append("外键：")
            for fk in table.foreign_keys:
                lines.append(f"- {fk.column} -> {fk.ref_table}.{fk.ref_column}")
        incoming = [
            f"- {fk.table}.{fk.column} -> 本表.{fk.ref_column}"
            for name in sorted(self.tables)
            for fk in self.tables[name].foreign_keys
            if fk.ref_table.lower() == table.name.lower()
        ]
        if incoming:
            lines.append("被引用：")
            lines.extend(incoming)
        if table.indexes:
            lines.append("索引：" + ", ".join(table.indexes))
        return "\n".join(lines)

    # ---------- 序列化（给前端） ----------

    def as_dict(self) -> dict:
        return {
            "db_path": self.db_path,
            "table_count": self.table_count,
            "column_count": self.column_count,
            "foreign_key_count": self.foreign_key_count,
            "tables": [
                {
                    "name": name,
                    "rows": self.tables[name].row_count,
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.type,
                            "pk": c.is_pk,
                            "notnull": c.notnull,
                        }
                        for c in self.tables[name].columns
                    ],
                }
                for name in sorted(self.tables)
            ],
        }


def _quote(name: str) -> str:
    return name if _IDENT_RE.match(name) else f'"{name}"'


# ---------------------------------------------------------------- 解析入口


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True, timeout=3.0)
    con.execute("PRAGMA query_only = ON")
    return con


def _fingerprint(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, int(stat.st_mtime_ns)


def load_schema(path: Path | str | None = None, force: bool = False) -> SchemaInfo:
    """解析数据库结构；同一文件未变更时复用缓存。"""
    db_path = Path(path or config.DB_PATH).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{db_path}")

    global _CACHE
    fp = _fingerprint(db_path)
    if not force and _CACHE and _CACHE.db_path == str(db_path) and _CACHE.fingerprint == fp:
        return _CACHE

    started = time.perf_counter()
    con = _connect_readonly(db_path)
    try:
        names = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables: dict[str, TableInfo] = {}
        for name in names:
            columns = [
                ColumnInfo(
                    name=row[1],
                    type=(row[2] or "").strip(),
                    notnull=bool(row[3]),
                    default=row[4],
                    pk=int(row[5] or 0),
                )
                for row in con.execute(f'PRAGMA table_info({_quote(name)})')
            ]
            fks = [
                ForeignKeyInfo(
                    table=name,
                    column=row[3],
                    ref_table=row[2],
                    ref_column=row[4],
                )
                for row in con.execute(f'PRAGMA foreign_key_list({_quote(name)})')
                if row[2] and row[3] and row[4]
            ]
            indexes = [
                row[1]
                for row in con.execute(f'PRAGMA index_list({_quote(name)})')
                if row[1]
            ]
            try:
                row_count = con.execute(f'SELECT COUNT(*) FROM {_quote(name)}').fetchone()[0]
            except sqlite3.Error:
                row_count = -1
            tables[name] = TableInfo(
                name=name,
                columns=columns,
                foreign_keys=fks,
                row_count=int(row_count),
                indexes=indexes,
            )

        # 记录日期字段的真实取值范围，避免模型把时间条件写在数据范围之外
        temporal: list[tuple[str, str, str, str]] = []
        for name, table in tables.items():
            for col in table.columns:
                ctype = (col.type or "").upper()
                looks_temporal = (
                    any(token in ctype for token in ("DATE", "TIME"))
                    or col.name.lower().endswith("date")
                )
                if not looks_temporal:
                    continue
                try:
                    row = con.execute(
                        f"SELECT MIN({_quote(col.name)}), MAX({_quote(col.name)}) "
                        f"FROM {_quote(name)}"
                    ).fetchone()
                except sqlite3.Error:
                    continue
                if row and row[0] is not None and row[1] is not None:
                    temporal.append((name, col.name, str(row[0]), str(row[1])))
    finally:
        con.close()

    elapsed_ms = (time.perf_counter() - started) * 1000
    info = SchemaInfo(
        db_path=str(db_path),
        tables=tables,
        built_at=time.time(),
        build_ms=elapsed_ms,
        fingerprint=fp,
        temporal=temporal,
    )
    _CACHE = info
    return info


_CACHE: SchemaInfo | None = None


def get_schema(force: bool = False) -> SchemaInfo:
    return load_schema(config.DB_PATH, force=force)
