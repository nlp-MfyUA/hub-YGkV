"""LangGraph StateGraph 顶层编排：解析 → 生成 → 复核（条件回炉 ≤3 轮）→ 执行 → 归纳。

与 week12（手写 for 循环编排）相比，这里把整个流程显式建模为一张图：

    START → parse_schema → generate → check ─┬─ approved → execute → summarize → END
                                             ├─ fatal / 轮次耗尽 → END
                                             └─ 未通过且未超轮次 → generate（带 feedback）

事件通道：节点内通过 `get_stream_writer()` 写 custom 事件，外层用
`graph.astream(state, stream_mode="custom")` 消费。事件形状与 week12 完全一致：
  {"type": "stage",  "stage": "...", "status": "...", "elapsed_ms": int, "payload": {...}}
  {"type": "delta",  "stage": "summarize", "text": "..."}
  {"type": "done",   "payload": {...}}
  {"type": "error",  "payload": {...}}
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

import config
from agent import check_agent, generate_agent, summarize_agent
from core import executor, guard
from core import llm as llm_mod
from core import schema as schema_mod


class ChatState(TypedDict, total=False):
    # ---- 输入 ----
    question: str
    history: list[dict]          # [{question, sql, answer}]，追问语境
    # ---- 每请求实例（在 pipeline 组装 initial state 时创建） ----
    generator: Any               # generate_agent.GenerateAgent
    reviewer: Any                # check_agent.CheckAgent
    # ---- 流程数据 ----
    started_at: float            # perf_counter 起点，供 total_ms
    schema_info: Any             # schema_mod.SchemaInfo
    rounds: int                  # 已完成的「生成+复核」轮数
    feedback: str | None         # 复核未通过时带给下一轮生成的回炉反馈
    sql: str
    review: Any                  # check_agent.ReviewResult | None
    fatal: bool                  # True 表示应立即结束（不可修复错误 / 轮次耗尽 / 执行失败）
    result: Any                  # core.executor.QueryResult
    answer: str
    usage_total: dict
    timings: list[dict]


def _stage(stage: str, status: str, elapsed_ms: float = 0.0, **payload) -> dict:
    return {
        "type": "stage",
        "stage": stage,
        "status": status,
        "elapsed_ms": int(round(elapsed_ms)),
        "payload": payload,
    }


def _error(stage: str, message: str, **payload) -> dict:
    return {"type": "error", "payload": {"stage": stage, "message": message, **payload}}


def _with_timing(state: ChatState, stage: str, elapsed_ms: float) -> list[dict]:
    timings = list(state.get("timings") or [])
    timings.append({"stage": stage, "elapsed_ms": int(elapsed_ms)})
    return timings


def _total_ms(state: ChatState) -> int:
    return int((time.perf_counter() - state["started_at"]) * 1000)


# ------------------------------------------------------------------ 节点


async def parse_schema(state: ChatState) -> dict:
    writer = get_stream_writer()
    started = time.perf_counter()
    writer(_stage("schema", "running"))
    try:
        info = schema_mod.get_schema()
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000
        writer(_stage("schema", "error", elapsed, message=str(exc)))
        writer(_error("schema", f"数据库结构解析失败：{exc}"))
        return {"fatal": True, "timings": _with_timing(state, "schema", elapsed)}

    elapsed = (time.perf_counter() - started) * 1000
    writer(_stage(
        "schema",
        "done",
        elapsed,
        table_count=info.table_count,
        column_count=info.column_count,
        foreign_key_count=info.foreign_key_count,
        db_path=info.db_path,
        cached_ms=round(info.build_ms, 1),
    ))
    return {"schema_info": info, "timings": _with_timing(state, "schema", elapsed)}


async def generate(state: ChatState) -> dict:
    writer = get_stream_writer()
    gen = state["generator"]
    gen.store["proposal"] = None  # 清掉上一轮残留，防止模型崩掉时拿到旧提案
    round_index = state.get("rounds", 0) + 1

    writer(_stage("generate", "running", round=round_index, max_rounds=config.MAX_REVIEW_ROUNDS))
    run, proposal = await generate_agent.generate_sql(
        state["question"],
        feedback=state.get("feedback"),
        history=state.get("history"),
        agent=gen,
    )
    usage_total = llm_mod.merge_usage(dict(state.get("usage_total") or {}), run.usage)

    if not proposal or not proposal.sql.strip():
        message = run.error or "模型未返回 SQL"
        writer(_stage(
            "generate",
            "error",
            run.elapsed_ms,
            round=round_index,
            message=message,
            tools=run.tools,
            usage=run.usage,
        ))
        review = check_agent.ReviewResult(
            approved=False,
            issues=[f"未能生成有效 SQL：{message}"],
            risk="high",
            source="static",
        )
        return {
            "rounds": round_index,
            "usage_total": usage_total,
            "review": review,
            "sql": "",
            "feedback": "上一次没有产出可执行的 SQL，请严格调用 submit_sql 提交一条 SELECT 查询。",
        }

    sql = proposal.sql
    writer(_stage(
        "generate",
        "done",
        run.elapsed_ms,
        round=round_index,
        max_rounds=config.MAX_REVIEW_ROUNDS,
        sql=sql,
        reasoning=proposal.reasoning,
        tables=proposal.tables,
        tools=run.tools,
        usage=run.usage,
        model=config.GENERATE_MODEL,
        fallback=proposal.fallback,
    ))
    return {
        "rounds": round_index,
        "usage_total": usage_total,
        "sql": sql,
        "review": None,
    }


async def check(state: ChatState) -> dict:
    writer = get_stream_writer()
    round_index = state["rounds"]
    sql = state["sql"]
    info = state["schema_info"]

    writer(_stage("check", "running", round=round_index))
    check_started = time.perf_counter()
    static = guard.check_static(sql, info)
    static_ms = (time.perf_counter() - check_started) * 1000

    if not static.ok:
        review = check_agent.ReviewResult(
            approved=False,
            issues=list(static.errors),
            risk="high",
            suggestion="；".join(static.warnings),
            source="static",
        )
        writer(_stage(
            "check",
            "done",
            static_ms,
            round=round_index,
            approved=False,
            issues=review.issues,
            risk="high",
            suggestion=review.suggestion,
            source="static",
            fatal=static.fatal,
            warnings=static.warnings,
            usage={},
        ))

        # 不可修复（写操作 / 非查询语句）：立即终止，不再消耗生成与复核轮次
        if static.fatal:
            writer(_error(
                "check",
                "该请求需要写入数据或变更表结构，本系统为只读模式，已拒绝执行。",
                rounds=round_index,
                sql=sql,
                fatal=True,
                total_ms=_total_ms(state),
            ))
            return {"review": review, "fatal": True}

        # 未通过：轮次耗尽则终止，否则带反馈回炉（与 LLM 复核未通过的路径同规则）
        if round_index >= config.MAX_REVIEW_ROUNDS:
            writer(_error(
                "check",
                f"复核连续 {config.MAX_REVIEW_ROUNDS} 轮未通过，已终止执行。",
                rounds=round_index,
                issues=review.issues,
                sql=sql,
                total_ms=_total_ms(state),
            ))
            return {"review": review, "fatal": True}

        return {
            "review": review,
            "feedback": guard.feedback_text(sql, review.issues),
            "timings": _with_timing(state, f"check#{round_index}", static_ms),
        }

    check_run, review = await check_agent.review_sql(
        state["question"],
        static.sql,
        agent=state["reviewer"],
        note="静态检查已通过；请重点核对 JOIN 关系、聚合口径与语义匹配。",
        history=state.get("history"),
    )
    usage_total = llm_mod.merge_usage(dict(state.get("usage_total") or {}), check_run.usage)
    check_ms = static_ms + check_run.elapsed_ms
    writer(_stage(
        "check",
        "done",
        check_ms,
        round=round_index,
        approved=review.approved,
        issues=review.issues,
        risk=review.risk,
        suggestion=review.suggestion,
        source=review.source,
        warnings=static.warnings,
        plan=static.validation.plan[:8] if static.validation else [],
        usage=check_run.usage,
        tools=check_run.tools,
        model=review.model or config.CHECK_MODEL,
        unrecoverable=review.unrecoverable,
    ))

    # 复核认定「诉求本身做不了」：重写 SQL 也无解，立即终止
    if review.unrecoverable and not review.approved:
        writer(_error(
            "check",
            "该诉求需要写入或变更数据，只读系统无法完成，已终止。",
            rounds=round_index,
            sql=static.sql,
            fatal=True,
            total_ms=_total_ms(state),
        ))
        return {"review": review, "sql": static.sql, "fatal": True}

    if review.approved:
        return {
            "review": review,
            "sql": static.sql,
            "usage_total": usage_total,
            "timings": _with_timing(state, f"check#{round_index}", check_ms),
        }

    # 未通过：轮次耗尽则终止，否则带反馈回炉
    if round_index >= config.MAX_REVIEW_ROUNDS:
        writer(_error(
            "check",
            f"复核连续 {config.MAX_REVIEW_ROUNDS} 轮未通过，已终止执行。",
            rounds=round_index,
            issues=review.issues,
            sql=static.sql,
            total_ms=_total_ms(state),
        ))
        return {"review": review, "sql": static.sql, "fatal": True}

    return {
        "review": review,
        "sql": static.sql,
        "usage_total": usage_total,
        "feedback": guard.feedback_text(static.sql, review.issues),
        "timings": _with_timing(state, f"check#{round_index}", check_ms),
    }


async def execute(state: ChatState) -> dict:
    writer = get_stream_writer()
    sql = state["sql"]

    writer(_stage("execute", "running"))
    try:
        # run_query 是同步阻塞调用（内置 5s 看门狗），放线程池避免拖住事件循环
        result = await asyncio.to_thread(executor.run_query, sql)
    except executor.QueryTimeout as exc:
        writer(_stage("execute", "error", 0, message=str(exc)))
        writer(_error("execute", str(exc)))
        return {"fatal": True}
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        writer(_stage("execute", "error", 0, message=message))
        writer(_error("execute", message))
        return {"fatal": True}

    writer(_stage(
        "execute",
        "done",
        result.elapsed_ms,
        sql=sql,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        max_rows=config.MAX_RESULT_ROWS,
    ))
    return {"result": result, "timings": _with_timing(state, "execute", result.elapsed_ms)}


async def summarize(state: ChatState) -> dict:
    writer = get_stream_writer()
    result = state["result"]

    writer(_stage("summarize", "running"))
    summarize_started = time.perf_counter()
    answer_parts: list[str] = []
    summarize_usage: dict = {}
    summarize_error: str | None = None
    async for chunk in summarize_agent.stream_summary(state["question"], result):
        if chunk["type"] == "delta":
            answer_parts.append(chunk["text"])
            writer({"type": "delta", "stage": "summarize", "text": chunk["text"]})
        else:
            summarize_usage = chunk.get("usage") or {}
            summarize_error = chunk.get("error")
            if not answer_parts and chunk.get("text"):
                answer_parts.append(chunk["text"])

    summarize_ms = (time.perf_counter() - summarize_started) * 1000
    usage_total = llm_mod.merge_usage(dict(state.get("usage_total") or {}), summarize_usage)
    answer = "".join(answer_parts).strip()

    if not answer:
        fallback = f"查询执行成功，共返回 {result.row_count} 行数据"
        if result.columns:
            fallback += f"，列包括：{'、'.join(result.columns)}"
        if result.truncated:
            fallback += f"（仅展示前 {config.MAX_RESULT_ROWS} 行）"
        fallback += "。自动归纳未生成内容，请查看上表结果。"
        answer = fallback
        for index in range(0, len(answer), 12):
            writer({"type": "delta", "stage": "summarize", "text": answer[index : index + 12]})

    writer(_stage(
        "summarize",
        "done" if not summarize_error else "error",
        summarize_ms,
        chars=len(answer),
        usage=summarize_usage,
        model=config.SUMMARY_MODEL,
        message=summarize_error,
    ))

    timings = _with_timing(state, "summarize", summarize_ms)
    writer({
        "type": "done",
        "payload": {
            "answer": answer,
            "sql": state["sql"],
            "rounds": state["rounds"],
            "total_ms": _total_ms(state),
            "usage": usage_total,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "timings": timings,
        },
    })
    return {"answer": answer, "usage_total": usage_total, "timings": timings}


# ------------------------------------------------------------------ 条件边


def route_after_check(state: ChatState) -> Literal["generate", "execute", "__end__"]:
    if state.get("fatal"):
        return END
    review = state.get("review")
    if review is not None and review.approved:
        return "execute"
    return "generate"


# ------------------------------------------------------------------ 组图


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("parse_schema", parse_schema)
    graph.add_node("generate", generate)
    graph.add_node("check", check)
    graph.add_node("execute", execute)
    graph.add_node("summarize", summarize)

    graph.add_edge(START, "parse_schema")
    graph.add_edge("parse_schema", "generate")
    graph.add_edge("generate", "check")
    graph.add_conditional_edges(
        "check",
        route_after_check,
        {"generate": "generate", "execute": "execute", END: END},
    )
    graph.add_edge("execute", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()
