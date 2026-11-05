r"""
作业一：用 LangGraph 复现 week11 的 SQL Agent Workflow。

week11 是一个手写的 7 阶段流水线；这里把每个阶段拆成 LangGraph 的一个节点，
用「条件边」表达校验失败后的改写循环，用 checkpointer 保存多轮对话历史。

    START
      │
   prepare            重置本轮字段，保留历史
      │
   select_tables      2. 表选择：LLM 选表 + 按外键补全 JOIN 路径
      │
   generate_sql       3. SQL 生成
      │
   validate_sql       4. SQL 校验：静态规则 + EXPLAIN 编译
      │  \
      │   \── 不通过且还有次数 ──> rewrite_sql ──┐
      │                                          │
      ├── 通过 ──> execute_sql                  │
      │              │  \                        │
      │              │   \── 执行报错 ────────────┘
      │              ├── 成功 ──> summarize ──> END
      │              └── 次数用尽 ──> fail ──> END
      │
      └── 次数用尽 ──> fail ──> END

运行：
    python sql_graph.py --demo                          # 跑内置的 5 个问题
    python sql_graph.py "每个国家的客户数量是多少？"      # 单个问题
    python sql_graph.py -i                              # 多轮交互（带记忆）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from dotenv import load_dotenv

# 作业二启动时会把本目录加入 sys.path，这里显式加载本目录的 .env
_ENV_FILE = Path(__file__).with_name(".env")
load_dotenv(_ENV_FILE)
load_dotenv()  # 也允许调用方在进程环境里配置

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from db_parser import DBParser  # noqa: E402
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
# 图状态
# --------------------------------------------------------------------------- #
class AgentState(TypedDict, total=False):
    """LangGraph 的共享状态。

    total=False 表示每个节点只需要返回自己更新的字段；
    其余字段由 checkpointer 从上一轮 / 上一个节点带过来。
    """

    question: str
    history: list[dict[str, Any]]  # 已完成的多轮对话（跨轮次保留）
    attempt: int                   # 当前是第几次生成 / 改写
    tables: list[str]
    table_reason: str
    sql: str
    sql_ok: bool
    error: str
    fatal: bool                    # LLM 调用失败等不可恢复错误，直接结束
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    ok: bool
    answer: str


# --------------------------------------------------------------------------- #
# 错误与结果数据结构
# --------------------------------------------------------------------------- #
class LLMError(RuntimeError):
    """大模型调用失败。"""


@dataclass
class Stage:
    name: str
    elapsed: float
    detail: str = ""


@dataclass
class WorkflowResult:
    question: str
    thread_id: str = ""
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
# 工具函数
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"```(?:json|sql)?\s*(.*?)```", re.S)


def strip_fence(text: str) -> str:
    """去掉 markdown 代码块围栏（模型经常不听话地加上）。"""
    match = _FENCE.search(text or "")
    return match.group(1).strip() if match else (text or "").strip()


def extract_json(text: str) -> dict:
    """从模型输出里抠出第一个 JSON 对象，解析失败抛 ValueError。"""
    raw = strip_fence(text)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"模型输出里没有 JSON 对象：{text[:200]!r}")
    return json.loads(raw[start : end + 1])


def _one_line(text: str, limit: int = 300) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_history(history: list[dict[str, Any]] | None, limit: int = 3) -> str:
    """把最近几轮对话整理成提示词文本。"""
    if not history:
        return "（无，这是当前对话的第一轮）"

    blocks: list[str] = []
    for index, turn in enumerate(history[-limit:], 1):
        blocks.append(
            f"第 {index} 轮\n"
            f"用户：{turn.get('question', '')}\n"
            f"SQL：{_one_line(turn.get('sql') or '（无）', 200)}\n"
            f"回答：{_one_line(turn.get('answer') or '（无）', 200)}"
        )
    return "\n\n".join(blocks)


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


# --------------------------------------------------------------------------- #
# LangGraph SQL Agent
# --------------------------------------------------------------------------- #
NODE_LABELS = {
    "prepare": "准备",
    "select_tables": "2. 表选择",
    "generate_sql": "3. SQL 生成",
    "validate_sql": "4. SQL 校验",
    "rewrite_sql": "5. SQL 改写",
    "execute_sql": "6. SQL 执行",
    "summarize": "7. 结果汇总",
    "fail": "查询失败",
}


def node_event(node: str, delta: dict[str, Any], elapsed: float) -> dict[str, Any]:
    """把一个 LangGraph 节点更新转换成前端 / CLI 都能消费的事件。"""
    detail = ""
    if node == "select_tables":
        tables = delta.get("tables") or []
        reason = delta.get("table_reason") or ""
        detail = ", ".join(tables) + (f"（{reason}）" if reason else "")
    elif node == "validate_sql":
        detail = "通过" if delta.get("sql_ok") else f"失败：{delta.get('error', '')}"
    elif node == "rewrite_sql":
        detail = f"第 {delta.get('attempt', '?')} 次尝试"
    elif node == "execute_sql":
        if delta.get("ok"):
            detail = f"返回 {len(delta.get('rows') or [])} 行"
            if delta.get("truncated"):
                detail += "（已截断）"
        else:
            detail = delta.get("error", "")
    elif node == "fail":
        detail = delta.get("error", "")

    return {
        "type": "stage",
        "node": node,
        "name": NODE_LABELS.get(node, node),
        "elapsed": round(elapsed, 3),
        "detail": detail,
        # 结构化字段，前端按需展示
        "tables": delta.get("tables"),
        "sql": delta.get("sql"),
        "sql_ok": delta.get("sql_ok"),
        "ok": delta.get("ok"),
        "attempt": delta.get("attempt"),
        "error": delta.get("error") or None,
        "row_count": len(delta["rows"]) if isinstance(delta.get("rows"), list) else None,
        "truncated": delta.get("truncated"),
    }


def final_payload(state: dict[str, Any]) -> dict[str, Any]:
    """图执行完成后，返回给前端 / CLI 的最终结果。"""
    return {
        "type": "final",
        "ok": bool(state.get("ok")),
        "answer": state.get("answer", ""),
        "sql": state.get("sql", ""),
        "tables": state.get("tables", []),
        "table_reason": state.get("table_reason", ""),
        "columns": state.get("columns", []),
        "rows": state.get("rows", []),
        "truncated": bool(state.get("truncated")),
        "error": state.get("error") or None,
    }


class SQLAgentGraph:
    """把 SQL Agent 的 7 个阶段编译成一张 LangGraph 图。"""

    def __init__(
        self,
        db_path: str | Path = "chinook.db",
        model: str | None = None,
        max_rewrite: int = 3,
        max_rows: int = 100,
        checkpointer: Any | None = None,
        inject_bad_sql: bool = False,
    ) -> None:
        start = time.perf_counter()
        self.parser = DBParser(db_path)
        self.parse_elapsed = time.perf_counter() - start

        self.max_rewrite = max_rewrite
        self.max_rows = max_rows
        # 仅用于演示「校验失败 -> 改写」循环：第一次生成故意注入一条引用了
        # 不存在字段的 SQL，后续由改写节点修复。
        self.inject_bad_sql = inject_bad_sql
        self.model_name = model or os.environ.get("LLM_MODEL", "deepseek-chat")
        self.llm = self._build_llm()
        self.checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self.graph = self._build_graph()

    # ------------------------------------------------------------------ #
    # 构建
    # ------------------------------------------------------------------ #
    def _build_llm(self) -> ChatOpenAI:
        api_key = os.environ.get("LLM_API_KEY")
        if not api_key:
            raise LLMError("缺少 LLM_API_KEY，请先把 .env.example 复制为 .env 并填入自己的 Key。")

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "api_key": api_key,
            "temperature": 0,
            "timeout": 90,
            "max_retries": 2,
        }
        base_url = os.environ.get("LLM_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    def _build_graph(self):
        builder = StateGraph(AgentState)

        builder.add_node("prepare", self._prepare)
        builder.add_node("select_tables", self._select_tables)
        builder.add_node("generate_sql", self._generate_sql)
        builder.add_node("validate_sql", self._validate_sql)
        builder.add_node("rewrite_sql", self._rewrite_sql)
        builder.add_node("execute_sql", self._execute_sql)
        builder.add_node("summarize", self._summarize)
        builder.add_node("fail", self._fail)

        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "select_tables")
        builder.add_edge("select_tables", "generate_sql")
        builder.add_edge("generate_sql", "validate_sql")
        builder.add_edge("rewrite_sql", "validate_sql")

        # 校验通过 -> 执行；否则改写，次数用尽 -> 失败
        builder.add_conditional_edges(
            "validate_sql",
            self._after_validate,
            {"execute": "execute_sql", "rewrite": "rewrite_sql", "fail": "fail"},
        )
        # 执行成功 -> 汇总；执行报错 -> 改写，次数用尽 -> 失败
        builder.add_conditional_edges(
            "execute_sql",
            self._after_execute,
            {"summarize": "summarize", "rewrite": "rewrite_sql", "fail": "fail"},
        )

        builder.add_edge("summarize", END)
        builder.add_edge("fail", END)

        return builder.compile(checkpointer=self.checkpointer)

    # ------------------------------------------------------------------ #
    # 节点
    # ------------------------------------------------------------------ #
    def _prepare(self, state: AgentState) -> dict[str, Any]:
        """每一轮开始时清空本轮字段；history 由 checkpointer 保留。"""
        return {
            "attempt": 0,
            "tables": [],
            "table_reason": "",
            "sql": "",
            "sql_ok": False,
            "error": "",
            "fatal": False,
            "columns": [],
            "rows": [],
            "truncated": False,
            "ok": False,
            "answer": "",
        }

    def _select_tables(self, state: AgentState) -> dict[str, Any]:
        """LLM 选表 -> 校验表名 -> 按外键补全 JOIN 路径。"""
        question = state.get("question", "")
        history_text = format_history(state.get("history"))

        try:
            data = extract_json(
                self._chat(
                    TABLE_SELECTION_SYSTEM,
                    TABLE_SELECTION_USER.format(
                        question=question,
                        history=history_text,
                        catalog=self.parser.get_catalog_text(),
                        relations=self.parser.get_relations_text(),
                    ),
                    json_mode=True,
                )
            )
        except (LLMError, ValueError) as exc:
            return {
                "tables": list(self.parser.table_names),
                "table_reason": f"选表失败，回退为全部表（{exc}）",
            }

        reason = str(data.get("reason", "")).strip()
        raw_tables = data.get("tables", [])
        if isinstance(raw_tables, str):
            raw_tables = [raw_tables]
        # 只保留真实存在的表，并去重保序
        tables = list(dict.fromkeys(t for t in raw_tables if t in self.parser.table_names))

        if not tables:
            return {
                "tables": list(self.parser.table_names),
                "table_reason": reason or "模型没有选出有效的表，回退为全部表",
            }

        completed = self._complete_join_path(tables)
        if len(completed) > len(tables):
            reason = f"{reason}；为连通关联表补充 {', '.join(t for t in completed if t not in tables)}"
        return {"tables": completed, "table_reason": reason}

    def _generate_sql(self, state: AgentState) -> dict[str, Any]:
        tables = state.get("tables") or list(self.parser.table_names)
        try:
            raw = self._chat(
                SQL_GENERATION_SYSTEM,
                SQL_GENERATION_USER.format(
                    question=state.get("question", ""),
                    history=format_history(state.get("history")),
                    schema=self.parser.get_schema_text(tables),
                    relations=self.parser.get_relations_text(tables),
                    samples=self.parser.get_samples_text(tables),
                ),
            )
        except LLMError as exc:
            return {
                "sql": "",
                "attempt": 1,
                "error": f"SQL 生成失败：{exc}",
                "fatal": True,
                "sql_ok": False,
            }

        sql = normalize_sql(raw)
        if self.inject_bad_sql:
            sql = "SELECT COUNT(*) FROM tracks WHERE GenreName = 'Rock'"
        return {"sql": sql, "attempt": 1, "error": "", "fatal": False, "sql_ok": False}

    def _validate_sql(self, state: AgentState) -> dict[str, Any]:
        """静态检查 + EXPLAIN 编译。"""
        if state.get("fatal"):
            # 生成 / 改写已经因为模型调用失败而终止，保留原始错误信息
            return {}
        sql = state.get("sql", "")
        ok, error = check_static(sql, self.parser.table_names)
        if ok:
            ok, error = self.parser.check_sql(sql)
        return {"sql_ok": ok, "error": "" if ok else error}

    def _rewrite_sql(self, state: AgentState) -> dict[str, Any]:
        attempt = int(state.get("attempt", 1)) + 1
        tables = state.get("tables") or list(self.parser.table_names)
        try:
            raw = self._chat(
                SQL_REWRITE_SYSTEM,
                SQL_REWRITE_USER.format(
                    question=state.get("question", ""),
                    history=format_history(state.get("history")),
                    sql=state.get("sql", ""),
                    error=state.get("error", ""),
                    schema=self.parser.get_schema_text(tables),
                ),
            )
        except LLMError as exc:
            return {
                "attempt": attempt,
                "error": f"SQL 改写失败：{exc}",
                "fatal": True,
            }

        return {"sql": normalize_sql(raw), "attempt": attempt, "error": "", "fatal": False}

    def _execute_sql(self, state: AgentState) -> dict[str, Any]:
        try:
            columns, rows, truncated = self.parser.execute_sql(
                state.get("sql", ""),
                max_rows=self.max_rows,
            )
        except Exception as exc:  # 超时 / 运行时错误 -> 交给改写节点
            return {"ok": False, "error": f"执行失败：{exc}"}
        return {
            "ok": True,
            "columns": columns,
            "rows": rows,
            "truncated": truncated,
            "error": "",
        }

    def _summarize(self, state: AgentState) -> dict[str, Any]:
        question = state.get("question", "")
        sql = state.get("sql", "")
        columns = state.get("columns") or []
        rows = state.get("rows") or []
        truncated = bool(state.get("truncated"))

        if not rows:
            answer = "没有查询到符合条件的数据，可能是筛选条件过严，或数据库中确实缺少对应记录。"
        else:
            try:
                answer = self._chat(
                    SUMMARY_SYSTEM,
                    SUMMARY_USER.format(
                        question=question,
                        history=format_history(state.get("history")),
                        sql=sql,
                        row_count=len(rows),
                        truncated_hint="，已截断" if truncated else "",
                        result_table=_rows_to_markdown(columns, rows, limit=30),
                    ),
                )
            except LLMError as exc:
                # 汇总失败不影响已经拿到的查询结果，退化成一句确定性描述
                first = ", ".join(f"{k}={v}" for k, v in list(rows[0].items())[:4])
                answer = f"查询返回 {len(rows)} 行数据。首行：{first}。（汇总失败：{exc}）"

        return {"answer": answer, "history": self._append_turn(state, answer)}

    def _fail(self, state: AgentState) -> dict[str, Any]:
        error = state.get("error") or "未知错误"
        answer = f"抱歉，没能生成可执行的 SQL：{error}"
        return {
            "ok": False,
            "answer": answer,
            "error": error,
            "history": self._append_turn(state, answer),
        }

    # ------------------------------------------------------------------ #
    # 路由
    # ------------------------------------------------------------------ #
    def _after_validate(self, state: AgentState) -> str:
        if state.get("fatal"):
            return "fail"
        if state.get("sql_ok"):
            return "execute"
        if int(state.get("attempt", 0)) < self.max_rewrite:
            return "rewrite"
        return "fail"

    def _after_execute(self, state: AgentState) -> str:
        if state.get("fatal"):
            return "fail"
        if state.get("ok"):
            return "summarize"
        if int(state.get("attempt", 0)) < self.max_rewrite:
            return "rewrite"
        return "fail"

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        """调一次模型；失败抛 LLMError。"""
        model = self.llm
        if json_mode:
            model = model.bind(response_format={"type": "json_object"})

        try:
            response = model.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
        except Exception as exc:
            raise LLMError(f"大模型调用失败：{exc}") from exc

        content = response.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return (content or "").strip()

    def _append_turn(self, state: AgentState, answer: str) -> list[dict[str, Any]]:
        """把本轮问答追加进历史，只保留最近 6 轮。"""
        history = list(state.get("history") or [])
        history.append(
            {
                "question": state.get("question", ""),
                "sql": state.get("sql", ""),
                "tables": list(state.get("tables") or []),
                "answer": answer,
            }
        )
        return history[-6:]

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

    # ------------------------------------------------------------------ #
    # 执行入口
    # ------------------------------------------------------------------ #
    def run(
        self,
        question: str,
        thread_id: str | None = None,
        trace: bool = True,
    ) -> WorkflowResult:
        """同步执行一轮问答，返回结构化结果（CLI / 测试使用）。"""
        question = (question or "").strip()
        if not question:
            raise ValueError("问题不能为空")

        thread_id = thread_id or uuid.uuid4().hex
        config = {"configurable": {"thread_id": thread_id}}
        result = WorkflowResult(question=question, thread_id=thread_id)

        result.stages.append(Stage("1. 数据库解析", self.parse_elapsed, self.parser.summary()))
        if trace:
            print(
                f"    [1. 数据库解析] {self.parser.summary()}"
                f"  ({self.parse_elapsed:.2f}s)  [thread {thread_id[:8]}]"
            )

        last = time.perf_counter()
        for update in self.graph.stream(
            {"question": question}, config, stream_mode="updates"
        ):
            elapsed = time.perf_counter() - last
            last = time.perf_counter()

            for node, delta in update.items():
                if node == "prepare":
                    continue
                event = node_event(node, delta, elapsed)
                result.stages.append(
                    Stage(event["name"], event["elapsed"], event["detail"])
                )
                self._apply_event(result, node, delta, event)
                if trace:
                    self._print_stage(event)

        final_state = self.graph.get_state(config).values
        result.ok = bool(final_state.get("ok"))
        result.answer = final_state.get("answer", "")
        result.sql = final_state.get("sql", "")
        result.tables = final_state.get("tables", [])
        result.table_reason = final_state.get("table_reason", "")
        result.columns = final_state.get("columns", [])
        result.rows = final_state.get("rows", [])
        result.truncated = bool(final_state.get("truncated"))
        result.error = final_state.get("error") or None

        return result

    def _apply_event(
        self,
        result: WorkflowResult,
        node: str,
        delta: dict[str, Any],
        event: dict[str, Any],
    ) -> None:
        if node == "select_tables":
            result.tables = delta.get("tables") or []
            result.table_reason = delta.get("table_reason") or ""
        elif node in {"generate_sql", "rewrite_sql"}:
            result.sql = delta.get("sql", "") or result.sql
            result.attempts.append(
                {
                    "attempt": delta.get("attempt"),
                    "sql": delta.get("sql", ""),
                    "ok": None,
                    "error": None,
                }
            )
        elif node == "validate_sql":
            if result.attempts:
                result.attempts[-1]["ok"] = bool(delta.get("sql_ok"))
                result.attempts[-1]["error"] = None if delta.get("sql_ok") else delta.get("error")
        elif node == "execute_sql":
            result.ok = bool(delta.get("ok"))
            if delta.get("ok"):
                result.columns = delta.get("columns") or []
                result.rows = delta.get("rows") or []
                result.truncated = bool(delta.get("truncated"))
            elif result.attempts:
                result.attempts[-1]["ok"] = False
                result.attempts[-1]["error"] = delta.get("error")
        elif node in {"summarize", "fail"}:
            result.answer = delta.get("answer", "")
        _ = event

    def _print_stage(self, event: dict[str, Any]) -> None:
        print(
            f"    [{event['name']}]"
            + (f" {event['detail']}" if event["detail"] else "")
            + f"  ({event['elapsed']:.2f}s)"
        )
        sql = event.get("sql")
        if sql and event["node"] in {"generate_sql", "rewrite_sql"}:
            print("      " + _one_line(sql, 400))

    def close(self) -> None:
        self.parser.close()

    def __enter__(self) -> "SQLAgentGraph":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# 兼容 week11 的类名
SQLAgent = SQLAgentGraph


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def print_result(result: WorkflowResult) -> None:
    print("\n" + "-" * 60)
    print(f"问题：{result.question}")
    print(f"选表：{', '.join(result.tables)}")
    print(f"SQL ：{_one_line(result.sql, 500)}")
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
    parser = argparse.ArgumentParser(description="基于 LangGraph + chinook.db 的 SQL Agent")
    parser.add_argument("question", nargs="?", help="自然语言问题")
    parser.add_argument("--demo", action="store_true", help="跑内置的演示问题")
    parser.add_argument("-i", "--interactive", action="store_true", help="多轮交互模式")
    parser.add_argument("--db", default=str(Path(__file__).with_name("chinook.db")), help="sqlite 数据库路径")
    parser.add_argument("--no-trace", action="store_true", help="不打印各阶段过程")
    parser.add_argument("--thread", help="会话 ID（同一 ID 共享多轮记忆）")
    parser.add_argument(
        "--inject-bad-sql",
        action="store_true",
        help="故障注入：第一次生成故意写错字段，演示「校验 -> 改写」循环",
    )
    args = parser.parse_args()

    if not (args.question or args.demo or args.interactive):
        parser.print_help()
        return

    trace = not args.no_trace
    with SQLAgentGraph(args.db, inject_bad_sql=args.inject_bad_sql) as agent:
        print(f"数据库：{args.db}（{len(agent.parser.table_names)} 张表）")
        print(f"模型  ：{agent.model_name}")
        print(f"框架  ：LangGraph StateGraph / 8 个节点 / 条件边改写循环")

        if args.demo:
            # 每个演示问题用独立 thread，避免上下文互相影响
            for question in DEMO_QUESTIONS:
                print(f"\n{'=' * 60}\n>>> {question}")
                print_result(agent.run(question, thread_id=uuid.uuid4().hex, trace=trace))
            return

        if args.question:
            print_result(agent.run(args.question, thread_id=args.thread, trace=trace))
            return

        # 交互模式：同一 thread 共享历史
        thread_id = args.thread or f"cli-{uuid.uuid4().hex[:8]}"
        print(f"\n会话 ID：{thread_id}")
        print("输入问题开始对话；/new 开新会话，/exit 退出。")
        while True:
            try:
                question = input("\n>>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question:
                continue
            if question.lower() in {"/exit", "/quit", "exit", "quit"}:
                break
            if question.lower() == "/new":
                thread_id = f"cli-{uuid.uuid4().hex[:8]}"
                print(f"已开启新会话：{thread_id}")
                continue
            print_result(agent.run(question, thread_id=thread_id, trace=trace))


if __name__ == "__main__":
    main()
