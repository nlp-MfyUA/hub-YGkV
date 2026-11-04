"""核心：LangGraph 把 Python for 循环改写成显式有向状态图。

节点：select_tables / generate_sql / validate_sql / execute_sql
     / repair_sql / summarize / finish_error
条件边：从校验或执行结果决定继续、修复还是停止。
"""

from __future__ import annotations
import sqlite3
from typing import TypedDict

from brains import SQLBrain
from db_tools import SQLiteTools


class SQLState(TypedDict, total=False):
    question: str
    tables: list[str]
    schema: str
    sql: str
    error: str
    answer: str
    columns: list[str]
    rows: list[list[str]]
    truncated: bool
    shown_rows: int
    repair_count: int
    trace: list[str]


def build_graph(db: SQLiteTools, brain: SQLBrain, max_repairs: int = 3):
    """构建并编译一个可复用的 StateGraph。不会在构建阶段调用 LLM。"""

    from langgraph.graph import StateGraph, START, END

    if max_repairs < 0:
        raise ValueError("max_repairs 不能小于 0")

    def log(state: SQLState, message: str) -> list[str]:
        return state.get("trace", []) + [message]

    # Node 1: 选表（LLM）
    def select_tables(state: SQLState) -> dict:
        plan = brain.choose_tables(state["question"], db.catalog_text())
        if plan.needs_clarification or not plan.tables:
            answer = plan.clarification_question or "无法确定需要查询哪些表。"
            return {
                "answer": answer,
                "error": "表选择阶段需要澄清",
                "trace": log(state, "select_tables: 需要澄清，提前结束"),
            }
        invalid = [name for name in plan.tables if name not in db.catalog]
        if invalid:
            return {
                "error": f"模型返回不存在的表：{invalid}",
                "trace": log(state, f"select_tables: 非法表 {invalid}"),
            }
        tables = list(dict.fromkeys(plan.tables))
        return {
            "tables": tables,
            "schema": db.schema_text(tables),
            "error": "",
            "trace": log(state, f"select_tables: {tables}"),
        }

    def route_selected(state: SQLState) -> str:
        return "stop" if state.get("error") else "continue"

    # Node 2: 生成 SQL（LLM）
    def generate_sql(state: SQLState) -> dict:
        draft = brain.generate_sql(state["question"], state["schema"])
        return {
            "sql": draft.sql,
            "error": "",
            "trace": log(state, f"generate_sql: {draft.sql}"),
        }

    # Node 3: 校验 SQL（确定性 Python）
    def validate_sql(state: SQLState) -> dict:
        try:
            checked = db.validate(state["sql"])
            return {
                "sql": checked,
                "error": "",
                "trace": log(state, "validate_sql: 通过"),
            }
        except (ValueError, sqlite3.Error) as exc:
            error = f"{type(exc).__name__}: {exc}"
            return {
                "error": error,
                "trace": log(state, f"validate_sql: 失败，{error}"),
            }

    def route_validation(state: SQLState) -> str:
        if not state.get("error"):
            return "execute"
        if state.get("repair_count", 0) < max_repairs:
            return "repair"
        return "stop"

    # Node 4: 执行 SQL（确定性 Python、只读连接）
    def execute_sql(state: SQLState) -> dict:
        try:
            result = db.execute(state["sql"])
            return {
                "columns": result.columns,
                "rows": result.rows,
                "shown_rows": result.shown_rows,
                "truncated": result.truncated,
                "error": "",
                "trace": log(
                    state,
                    f"execute_sql: 成功，显示 {result.shown_rows} 行"
                    + ("（已截断）" if result.truncated else ""),
                ),
            }
        except (ValueError, sqlite3.Error) as exc:
            error = f"{type(exc).__name__}: {exc}"
            return {
                "error": error,
                "trace": log(state, f"execute_sql: 失败，{error}"),
            }

    def route_execution(state: SQLState) -> str:
        if not state.get("error"):
            return "summarize"
        if state.get("repair_count", 0) < max_repairs:
            return "repair"
        return "stop"

    # Node 5: 修复 SQL（LLM）。每次执行都会增加共享 State 中的计数。
    def repair_sql(state: SQLState) -> dict:
        fixed = brain.repair_sql(
            state["question"],
            state["schema"],
            state["sql"],
            state["error"],
        )
        count = state.get("repair_count", 0) + 1
        return {
            "sql": fixed.sql,
            "repair_count": count,
            "error": "",
            "trace": log(state, f"repair_sql: 第 {count} 次修复 -> {fixed.sql}"),
        }

    # Node 6: 汇总结果（LLM；空结果直接用代码返回）
    def summarize(state: SQLState) -> dict:
        if not state.get("rows"):
            answer = "未查询到符合条件的数据。"
        else:
            report = brain.summarize(
                state["question"],
                state["sql"],
                state["columns"],
                state["rows"],
                state.get("truncated", False),
            )
            answer = report.answer
        return {
            "answer": answer,
            "trace": log(state, "summarize: 完成"),
        }

    # Node 7: 错误出口（不会无限重试）
    def finish_error(state: SQLState) -> dict:
        answer = state.get("answer") or (
            f"SQL Agent 未能完成查询：{state.get('error', '未知错误')}。"
            f" 已尝试修复 {state.get('repair_count', 0)} 次。"
        )
        return {
            "answer": answer,
            "trace": log(state, "finish_error: 结束"),
        }

    builder = StateGraph(SQLState)
    builder.add_node("select_tables", select_tables)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("validate_sql", validate_sql)
    builder.add_node("execute_sql", execute_sql)
    builder.add_node("repair_sql", repair_sql)
    builder.add_node("summarize", summarize)
    builder.add_node("finish_error", finish_error)

    builder.add_edge(START, "select_tables")
    builder.add_conditional_edges(
        "select_tables", route_selected,
        {"continue": "generate_sql", "stop": "finish_error"}
    )
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_conditional_edges(
        "validate_sql", route_validation,
        {"execute": "execute_sql", "repair": "repair_sql", "stop": "finish_error"}
    )
    builder.add_conditional_edges(
        "execute_sql", route_execution,
        {"summarize": "summarize", "repair": "repair_sql", "stop": "finish_error"}
    )
    builder.add_edge("repair_sql", "validate_sql")
    builder.add_edge("summarize", END)
    builder.add_edge("finish_error", END)

    # compile() 之后才能 invoke()/stream()。
    return builder.compile()
