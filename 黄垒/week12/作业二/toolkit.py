"""给 LangChain Agent 用的 SQL 工具集。

三个工具对应 week11 Workflow 里的三个阶段，但控制权交给模型：
    list_tables  <- 阶段 2 表选择前的「表目录」
    get_schema   <- 阶段 2/3 的 schema + 外键 + 样例（自动补 JOIN 路径）
    run_sql      <- 阶段 4/5/6 校验 + 执行；报错原样返回给模型，由模型改写

安全边界不依赖模型自觉：
    - 数据库以只读方式打开（mode=ro + PRAGMA query_only）
    - 静态检查只允许单条 SELECT / WITH，禁止写操作关键字
    - EXPLAIN 预编译，字段名 / 语法错误在真正执行前暴露
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain.tools import tool

from db_parser import DBParser
from sql_guard import check_static, normalize_sql


@dataclass
class ExecutedSQL:
    sql: str
    ok: bool
    rows: int = 0
    error: str = ""
    elapsed: float = 0.0


@dataclass
class ToolEvent:
    name: str
    args: dict[str, Any]
    result: str
    elapsed: float


@dataclass
class SQLToolkit:
    parser: DBParser
    max_rows: int = 50
    executed: list[ExecutedSQL] = field(default_factory=list)
    events: list[ToolEvent] = field(default_factory=list)
    on_event: Callable[[ToolEvent], None] | None = None

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    def as_tools(self) -> list:
        parser = self.parser
        toolkit = self

        @tool
        def list_tables() -> str:
            """列出数据库中的所有表（表名、行数、字段、样例行）。回答任何问题前先调用它。"""
            started = time.perf_counter()
            result = parser.get_catalog_text()
            toolkit._record("list_tables", {}, result, started)
            return result

        @tool
        def get_schema(tables: str) -> str:
            """获取指定表的完整结构、字段统计、外键关系和样例行。

            Args:
                tables: 表名，多个表用英文或中文逗号分隔，例如 "albums, artists"。
            """
            started = time.perf_counter()
            names = _parse_tables(tables)
            if not names:
                result = "错误：没有提供表名。请传入逗号分隔的表名，例如 \"albums, artists\"。"
                toolkit._record("get_schema", {"tables": tables}, result, started)
                return result

            unknown = [name for name in names if name not in parser.table_names]
            if unknown:
                result = (
                    f"错误：数据库中不存在表 {', '.join(unknown)}。"
                    f"可用的表：{', '.join(parser.table_names)}"
                )
                toolkit._record("get_schema", {"tables": tables}, result, started)
                return result

            completed = _complete_join_path(parser, names)
            blocks = [parser.get_schema_text(completed)]

            added = [name for name in completed if name not in names]
            if added:
                blocks.append(
                    "【自动补充的关联表】" + ", ".join(added) + "（为了让多表 JOIN 能连通）"
                )
            blocks.append("【外键关系】\n" + parser.get_relations_text(completed))
            blocks.append("【样例行】\n" + parser.get_samples_text(completed))

            result = "\n\n".join(blocks)
            toolkit._record("get_schema", {"tables": tables}, result, started)
            return result

        @tool
        def run_sql(sql: str) -> str:
            """校验并执行一条 SQLite SELECT，返回查询结果；失败时返回错误原因，供你修正 SQL。

            Args:
                sql: 一条 SELECT（或 WITH ... SELECT）语句，不要加分号。
            """
            started = time.perf_counter()
            cleaned = normalize_sql(sql)

            def fail(message: str) -> str:
                toolkit.executed.append(
                    ExecutedSQL(sql=cleaned, ok=False, error=message,
                                elapsed=time.perf_counter() - started)
                )
                result = (
                    f"SQL 执行失败：{message}\n"
                    f"当前 SQL：{cleaned}\n"
                    "请阅读错误信息，修正 SQL 后再次调用 run_sql（不要重复同样的错误）。"
                )
                toolkit._record("run_sql", {"sql": cleaned}, result, started)
                return result

            if not cleaned:
                return fail("SQL 为空")

            # 同一条 SQL 连续失败 3 次，说明模型没有读懂错误，继续重试只会浪费调用
            if len([item for item in toolkit.executed[-2:] if item.sql == cleaned and not item.ok]) == 2:
                result = (
                    "同一条 SQL 已经连续失败 3 次，请停止重试。"
                    "直接向用户说明当前无法完成查询，以及可能的原因。"
                )
                toolkit._record("run_sql", {"sql": cleaned}, result, started)
                return result

            ok, error = check_static(cleaned, parser.table_names)
            if not ok:
                return fail(error)

            ok, error = parser.check_sql(cleaned)
            if not ok:
                return fail(error)

            try:
                columns, rows, truncated = parser.execute_sql(cleaned, max_rows=self.max_rows)
            except Exception as exc:
                return fail(f"执行报错：{exc}")

            toolkit.executed.append(
                ExecutedSQL(sql=cleaned, ok=True, rows=len(rows),
                            elapsed=time.perf_counter() - started)
            )
            if not rows:
                result = "执行成功，返回 0 行。可以据此回答「没有查询到符合条件的数据」。"
            else:
                result = (
                    f"执行成功，返回 {len(rows)} 行"
                    + ("（已截断，仅展示前 50 行）" if truncated else "")
                    + "：\n"
                    + _rows_to_markdown(columns, rows)
                    + "\n请基于这些真实结果用中文回答，不要编造数据。"
                )
            toolkit._record("run_sql", {"sql": cleaned}, result, started)
            return result

        return [list_tables, get_schema, run_sql]

    # ------------------------------------------------------------------ #
    def _record(self, name: str, args: dict[str, Any], result: str, started: float) -> None:
        event = ToolEvent(
            name=name,
            args=args,
            result=result,
            elapsed=time.perf_counter() - started,
        )
        self.events.append(event)
        if self.on_event:
            self.on_event(event)


# ---------------------------------------------------------------------- #
# 辅助函数
# ---------------------------------------------------------------------- #
def _parse_tables(text: str) -> list[str]:
    names = [part.strip() for part in re.split(r"[,，、\s]+", text or "") if part.strip()]
    return list(dict.fromkeys(names))


def _complete_join_path(parser: DBParser, tables: list[str]) -> list[str]:
    """把选中表之间最短外键路径上的中间表补上（BFS）。"""
    graph: dict[str, set[str]] = defaultdict(set)
    for fk in parser.foreign_keys:
        a, b = fk["constrained_table"], fk["referred_table"]
        graph[a].add(b)
        graph[b].add(a)

    def shortest_path(src: str, dst: str) -> list[str]:
        if src == dst:
            return [src]
        parent: dict[str, str | None] = {src: None}
        queue = deque([src])
        while queue:
            node = queue.popleft()
            for nxt in sorted(graph[node]):
                if nxt in parent:
                    continue
                parent[nxt] = node
                if nxt == dst:
                    path, cur = [], dst
                    while cur is not None:
                        path.append(cur)
                        cur = parent[cur]
                    return path[::-1]
                queue.append(nxt)
        return []

    result = list(tables)
    for src in tables:
        for dst in tables:
            for node in shortest_path(src, dst):
                if node not in result:
                    result.append(node)
    return result


def _rows_to_markdown(columns: list[str], rows: list[dict[str, Any]], width: int = 48) -> str:
    def cell(value: Any) -> str:
        text = "" if value is None else str(value).replace("\n", " ").replace("|", "\\|")
        return text if len(text) <= width else text[: width - 3] + "..."

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(row.get(col)) for col in columns) + " |")
    return "\n".join(lines)
