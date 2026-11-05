"""
作业一：基于 chinook.db 的完整 SQL Agent Workflow


    1. 数据库解析    DBParser：表 / 字段 / 外键 / 字段统计 / 样例数据（纯代码，无 LLM）
    2. 表选择        LLM 从表目录里挑出需要的表，再按外键补全 JOIN 路径
    3. SQL 生成      LLM 根据选中的表写 SQLite SQL
    4. SQL 校验      静态检查（单条 SELECT、禁止写操作、表必须存在）+ EXPLAIN 编译
    5. SQL 改写     校验 / 执行失败时，把报错喂回模型重写，最多 max_rewrite 次
    6. SQL 执行      只读连接执行，带行数上限和超时中断
    7. 结果汇总      LLM 把查询结果总结成中文结论

运行：
    python sql_agent.py --demo                          # 跑内置的 5 个问题
    python sql_agent.py "每个国家的客户数量是多少？"      # 单个问题
    python sql_agent.py -i                              # 交互模式
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from db_parser import DBParser  # noqa: E402
from llm import LLMClient, LLMError, extract_json  # noqa: E402
from prompts import (  # noqa: E402
    SQL_GENERATION_SYSTEM,
    SQL_GENERATION_USER,
    SQL_REWRITE_SYSTEM,
    SQL_REWRITE_USER,
    SUMMARY_SYSTEM,
    SUMMARY_USER,
    TABLE_SELECTION_SYSTEM,
    TABLE_SELECTION_USER,
)
from sql_guard import check_static, normalize_sql  # noqa: E402

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 结果数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Stage:
    name: str
    elapsed: float
    detail: str = ""


@dataclass
class WorkflowResult:
    question: str
    ok: bool = False
    tables: list[str] = field(default_factory=list)
    table_reason: str = ""
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    answer: str = ""
    error: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    stages: list[Stage] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Workflow
# --------------------------------------------------------------------------- #
class SQLAgent:
    def __init__(
        self,
        db_path: str | Path = "chinook.db",
        llm: LLMClient | None = None,
        max_rewrite: int = 3,
        max_rows: int = 100,
        trace: bool = True,
    ) -> None:
        self.parser = DBParser(db_path)
        self.llm = llm or LLMClient()
        self.max_rewrite = max_rewrite
        self.max_rows = max_rows
        self.trace = trace

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #
    def run(self, question: str) -> WorkflowResult:
        question = (question or "").strip()
        if not question:
            raise ValueError("问题不能为空")

        result = WorkflowResult(question=question)

        # ---- 阶段 1：数据库解析（构造 SQLAgent 时已完成，这里只记录摘要）----
        self._record(
            result,
            "1. 数据库解析",
            0.0,
            f"{len(self.parser.table_names)} 张表 / "
            f"{sum(len(v) for v in self.parser._table_fields.values())} 个字段 / "
            f"{len(self.parser.foreign_keys)} 条外键",
        )

        # ---- 阶段 2：表选择 ----
        start = time.perf_counter()
        tables, reason = self._select_tables(question)
        result.tables, result.table_reason = tables, reason
        self._record(result, "2. 表选择", time.perf_counter() - start, ", ".join(tables) + f"（{reason}）")

        # ---- 阶段 3-6：生成 -> 校验 -> 改写 -> 执行 ----
        sql = ""
        last_error = ""
        columns: list[str] = []
        rows: list[dict[str, Any]] = []
        truncated = False

        for attempt in range(1, self.max_rewrite + 1):
            # 3. 生成 / 5. 改写
            start = time.perf_counter()
            if attempt == 1:
                raw = self._generate_sql(question, tables)
                self._record(result, "3. SQL 生成", time.perf_counter() - start)
            else:
                raw = self._rewrite_sql(question, sql, last_error, tables)
                self._record(result, "5. SQL 改写", time.perf_counter() - start, f"第 {attempt} 次尝试")
            sql = normalize_sql(raw)
            if self.trace:
                print("      " + sql.replace("\n", " "))

            # 4. 校验：静态检查 + EXPLAIN 编译
            start = time.perf_counter()
            ok, error = check_static(sql, self.parser.table_names)
            if ok:
                ok, error = self.parser.check_sql(sql)
            self._record(result, "4. SQL 校验", time.perf_counter() - start, "通过" if ok else f"失败：{error}")

            attempt_info = {"attempt": attempt, "sql": sql, "ok": ok, "error": None if ok else error}
            result.attempts.append(attempt_info)

            if not ok:
                last_error = error
                continue

            # 6. 执行
            start = time.perf_counter()
            try:
                columns, rows, truncated = self.parser.execute_sql(sql, max_rows=self.max_rows)
            except Exception as exc:  # 超时 / 运行时错误 -> 交给改写阶段
                last_error = f"执行失败：{exc}"
                attempt_info.update(ok=False, error=last_error)
                self._record(result, "6. SQL 执行", time.perf_counter() - start, last_error)
                continue

            self._record(
                result,
                "6. SQL 执行",
                time.perf_counter() - start,
                f"返回 {len(rows)} 行" + ("（已截断）" if truncated else ""),
            )
            result.ok = True
            break

        if not result.ok:
            result.error = last_error
            result.sql = sql
            result.answer = f"抱歉，没能生成可执行的 SQL：{last_error}"
            self._record(result, "7. 结果汇总", 0.0, "跳过（执行失败）")
            return result

        result.sql = sql
        result.columns, result.rows, result.truncated = columns, rows, truncated

        # ---- 阶段 7：结果汇总 ----
        start = time.perf_counter()
        result.answer = self._summarize(question, sql, columns, rows, truncated)
        self._record(result, "7. 结果汇总", time.perf_counter() - start)

        return result

    # ------------------------------------------------------------------ #
    # 阶段实现
    # ------------------------------------------------------------------ #
    def _select_tables(self, question: str) -> tuple[list[str], str]:
        """LLM 选表 -> 校验表名 -> 按外键补全 JOIN 路径。"""
        user = TABLE_SELECTION_USER.format(
            question=question,
            catalog=self.parser.get_catalog_text(),
            relations=self.parser.get_relations_text(),
        )
        reason = ""
        tables: list[str] = []

        try:
            data = extract_json(self.llm.chat(TABLE_SELECTION_SYSTEM, user, json_mode=True))
            reason = str(data.get("reason", "")).strip()
            raw_tables = data.get("tables", [])
            if isinstance(raw_tables, str):
                raw_tables = [raw_tables]
            # 只保留真实存在的表，并去重保序
            tables = list(dict.fromkeys(t for t in raw_tables if t in self.parser.table_names))
        except (LLMError, ValueError) as exc:
            reason = f"选表失败，回退为全部表（{exc}）"

        if not tables:
            return list(self.parser.table_names), reason

        completed = self._complete_join_path(tables)
        if len(completed) > len(tables):
            reason = f"{reason}；为连通关联表补充 {', '.join(t for t in completed if t not in tables)}"
        return completed, reason

    def _complete_join_path(self, tables: list[str]) -> list[str]:
        """把选中表之间最短 JOIN 路径上的中间表补上。

        例如模型选了 tracks 和 genres，中间缺少什么就补什么；
        这样即使模型漏掉关联表，生成的 SQL 也不会因为缺 JOIN 而报错。
        """
        graph: dict[str, set[str]] = defaultdict(set)
        for fk in self.parser.foreign_keys:
            a, b = fk["constrained_table"], fk["referred_table"]
            graph[a].add(b)
            graph[b].add(a)

        selected = set(tables)

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

    def _generate_sql(self, question: str, tables: list[str]) -> str:
        return self.llm.chat(
            SQL_GENERATION_SYSTEM,
            SQL_GENERATION_USER.format(
                question=question,
                schema=self.parser.get_schema_text(tables),
                relations=self.parser.get_relations_text(tables),
                samples=self.parser.get_samples_text(tables),
            ),
        )

    def _rewrite_sql(self, question: str, sql: str, error: str, tables: list[str]) -> str:
        return self.llm.chat(
            SQL_REWRITE_SYSTEM,
            SQL_REWRITE_USER.format(
                question=question,
                sql=sql,
                error=error,
                schema=self.parser.get_schema_text(tables),
            ),
        )

    def _summarize(
        self,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        truncated: bool,
    ) -> str:
        if not rows:
            return "没有查询到符合条件的数据，可能是筛选条件过严，或数据库中确实缺少对应记录。"

        try:
            return self.llm.chat(
                SUMMARY_SYSTEM,
                SUMMARY_USER.format(
                    question=question,
                    sql=sql,
                    row_count=len(rows),
                    truncated_hint="，已截断" if truncated else "",
                    result_table=_rows_to_markdown(columns, rows, limit=30),
                ),
            )
        except LLMError as exc:
            # 汇总失败不影响已经拿到的查询结果，退化成一句确定性描述
            first = ", ".join(f"{k}={v}" for k, v in list(rows[0].items())[:4])
            return f"查询返回 {len(rows)} 行数据。首行：{first}。（汇总失败：{exc}）"

    # ------------------------------------------------------------------ #
    # 输出
    # ------------------------------------------------------------------ #
    def _record(self, result: WorkflowResult, name: str, elapsed: float, detail: str = "") -> None:
        result.stages.append(Stage(name=name, elapsed=elapsed, detail=detail))
        if not self.trace:
            return
        print(f"    [{name}]" + (f" {detail}" if detail else "") + f"  ({elapsed:.2f}s)")

    def close(self) -> None:
        self.parser.close()

    def __enter__(self) -> "SQLAgent":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _rows_to_markdown(columns: list[str], rows: list[dict[str, Any]], limit: int = 30) -> str:
    """把查询结果转成 markdown 表格，喂给汇总提示词（控制行数，避免提示词过长）。"""
    if not rows:
        return "（空）"

    def cell(value: Any, width: int = 40) -> str:
        text = "" if value is None else str(value).replace("\n", " ").replace("|", "\\|")
        return text if len(text) <= width else text[: width - 3] + "..."

    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(cell(row.get(c)) for c in columns) + " |")
    if len(rows) > limit:
        lines.append(f"| （其余 {len(rows) - limit} 行略） |")
    return "\n".join(lines)


def print_result(result: WorkflowResult) -> None:
    print("\n" + "-" * 60)
    print(f"问题：{result.question}")
    print(f"选表：{', '.join(result.tables)}")
    print(f"SQL ：{result.sql.replace(chr(10), ' ')}")
    if result.attempts and len(result.attempts) > 1:
        for item in result.attempts[:-1]:
            print(f"  ↳ 第 {item['attempt']} 次失败：{item['error']}")
    if result.ok and result.rows:
        print(f"结果：{len(result.rows)} 行" + ("（已截断）" if result.truncated else ""))
    print(f"回答：{result.answer}")
    print("-" * 60)


DEMO_QUESTIONS = [
    "每个国家的客户数量是多少？按客户数从多到少排序，取前 5 个。",
    "销售额最高的 5 位客户是谁？请给出客户姓名和总消费金额。",
    "Rock 类型的歌曲一共有多少首？",
    "每位艺术家的专辑数量，取前 3 名。",
    "2009 年每个月的总销售额是多少？",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="基于 chinook.db 的 SQL Agent Workflow")
    parser.add_argument("question", nargs="?", help="自然语言问题")
    parser.add_argument("--demo", action="store_true", help="跑内置的演示问题")
    parser.add_argument("-i", "--interactive", action="store_true", help="交互模式，输入空行退出")
    parser.add_argument("--db", default=str(Path(__file__).with_name("chinook.db")), help="sqlite 数据库路径")
    parser.add_argument("--no-trace", action="store_true", help="不打印各阶段过程")
    args = parser.parse_args()

    if not (args.question or args.demo or args.interactive):
        parser.print_help()
        return

    with SQLAgent(args.db, trace=not args.no_trace) as agent:
        print(f"数据库：{args.db}（{len(agent.parser.table_names)} 张表）")

        if args.demo:
            for question in DEMO_QUESTIONS:
                print(f"\n{'=' * 60}\n>>> {question}")
                print_result(agent.run(question))
            return

        if args.question:
            print_result(agent.run(args.question))
            return

        # 交互模式
        while True:
            try:
                question = input("\n请输入问题（回车退出）：").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question:
                break
            print_result(agent.run(question))


if __name__ == "__main__":
    main()
