"""Stage 1 · 数据库解析。

职责：连接数据库，抽取完整 schema（表 / 列 / 类型 / 主外键 / 行数 /
低基数列取值 / 样例行），构造后续所有 stage 共用的 DatabaseSchema。
"""
from __future__ import annotations

import time
from pathlib import Path

from ..db import DatabaseSchema, build_database, connect_readonly, parse_schema
from ..models import STATUS_OK, STAGE_DB_PARSE, StageTrace


class DatabaseParserStage:
    name = STAGE_DB_PARSE

    def __init__(self, db_path: str | Path, *, ensure_built: bool = False):
        self._db_path = Path(db_path)
        self._ensure_built = ensure_built

    def run(self) -> tuple[DatabaseSchema, StageTrace]:
        start = time.perf_counter()
        if self._ensure_built or not self._db_path.exists():
            build_database(self._db_path)
        conn = connect_readonly(self._db_path)
        try:
            schema = parse_schema(conn)
        finally:
            conn.close()
        duration_ms = (time.perf_counter() - start) * 1000
        summary = "；".join(
            f"{t} {schema.tables[t].row_count} 行" for t in schema.table_names
        )
        trace = StageTrace(
            stage=self.name,
            status=STATUS_OK,
            input_brief=str(self._db_path),
            output_brief=f"{len(schema.tables)} 张表（{summary}）",
            detail="已抽取表/列/类型/主外键/行数/低基数列取值/样例行",
            duration_ms=duration_ms,
        )
        return schema, trace
