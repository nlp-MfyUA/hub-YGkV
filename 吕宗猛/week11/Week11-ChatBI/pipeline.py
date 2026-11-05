"""流程编排：结构解析 → 生成 → 复核（≤3 轮）→ 执行 → 流式归纳。

对外是一个异步事件流，事件形状：
  {"type": "stage", "stage": "schema|generate|check|execute|summarize",
   "status": "running|done|error", "elapsed_ms": int, "payload": {...}}
  {"type": "delta", "stage": "summarize", "text": "..."}
  {"type": "done", "payload": {"answer": "...", "total_ms": int, ...}}
  {"type": "error", "payload": {"stage": "...", "message": "..."}}
"""

from __future__ import annotations

import time
from typing import AsyncIterator

import config
from agent import check_agent, generate_agent, summarize_agent
from core import executor, guard, llm
from core import schema as schema_mod


def _stage(stage: str, status: str, elapsed_ms: float = 0.0, **payload) -> dict:
    return {
        "type": "stage",
        "stage": stage,
        "status": status,
        "elapsed_ms": int(round(elapsed_ms)),
        "payload": payload,
    }


def _format_feedback(sql: str, issues: list[str]) -> str:
    return guard.feedback_text(sql, issues)


async def run_pipeline(question: str) -> AsyncIterator[dict]:
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "payload": {"stage": "input", "message": "问题不能为空"}}
        return

    total_started = time.perf_counter()
    usage_total: dict = {}
    timings: list[dict] = []

    # ---------- ① 结构解析 ----------
    stage_started = time.perf_counter()
    yield _stage("schema", "running")
    try:
        info = schema_mod.get_schema()
    except Exception as exc:  # noqa: BLE001
        yield _stage("schema", "error", (time.perf_counter() - stage_started) * 1000, message=str(exc))
        yield {"type": "error", "payload": {"stage": "schema", "message": f"数据库结构解析失败：{exc}"}}
        return
    schema_ms = (time.perf_counter() - stage_started) * 1000
    timings.append({"stage": "schema", "elapsed_ms": int(schema_ms)})
    yield _stage(
        "schema",
        "done",
        schema_ms,
        table_count=info.table_count,
        column_count=info.column_count,
        foreign_key_count=info.foreign_key_count,
        db_path=info.db_path,
        cached_ms=round(info.build_ms, 1),
    )

    generator = generate_agent.build_agent(info)
    reviewer = check_agent.build_agent(info)

    # ---------- ②③ 生成 + 复核（最多 MAX_REVIEW_ROUNDS 轮） ----------
    approved = False
    last_sql = ""
    last_review: check_agent.ReviewResult | None = None
    feedback: str | None = None
    rounds_used = 0

    for round_index in range(1, config.MAX_REVIEW_ROUNDS + 1):
        rounds_used = round_index

        yield _stage("generate", "running", round=round_index, max_rounds=config.MAX_REVIEW_ROUNDS)
        run, proposal = await generate_agent.generate_sql(
            question, feedback=feedback, agent=generator
        )
        llm.merge_usage(usage_total, run.usage)

        if not proposal or not proposal.sql.strip():
            message = run.error or "模型未返回 SQL"
            yield _stage(
                "generate",
                "error",
                run.elapsed_ms,
                round=round_index,
                message=message,
                tools=run.tools,
                usage=run.usage,
            )
            last_review = check_agent.ReviewResult(
                approved=False,
                issues=[f"未能生成有效 SQL：{message}"],
                risk="high",
                source="static",
            )
            feedback = "上一次没有产出可执行的 SQL，请严格调用 submit_sql 提交一条 SELECT 查询。"
            continue

        sql = proposal.sql
        last_sql = sql
        yield _stage(
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
        )

        # ---- 复核：先静态，再语义 ----
        yield _stage("check", "running", round=round_index)
        stage_started = time.perf_counter()
        static = guard.check_static(sql, info)
        static_ms = (time.perf_counter() - stage_started) * 1000

        if not static.ok:
            last_review = check_agent.ReviewResult(
                approved=False,
                issues=list(static.errors),
                risk="high",
                suggestion="；".join(static.warnings),
                source="static",
            )
            yield _stage(
                "check",
                "done",
                static_ms,
                round=round_index,
                approved=False,
                issues=last_review.issues,
                risk="high",
                suggestion=last_review.suggestion,
                source="static",
                fatal=static.fatal,
                warnings=static.warnings,
                usage={},
            )
            timings.append({"stage": f"check#{round_index}", "elapsed_ms": int(static_ms)})

            # 不可修复（写操作 / 非查询语句）：立即终止，不再消耗生成与复核轮次
            if static.fatal:
                yield {
                    "type": "error",
                    "payload": {
                        "stage": "check",
                        "message": "该请求需要写入数据或变更表结构，本系统为只读模式，已拒绝执行。",
                        "rounds": round_index,
                        "sql": sql,
                        "fatal": True,
                        "total_ms": int((time.perf_counter() - total_started) * 1000),
                    },
                }
                return

            feedback = _format_feedback(sql, last_review.issues)
            continue

        check_run, review = await check_agent.review_sql(
            question,
            static.sql,
            agent=reviewer,
            note="静态检查已通过；请重点核对 JOIN 关系、聚合口径与语义匹配。",
        )
        llm.merge_usage(usage_total, check_run.usage)
        last_review = review
        approved = review.approved
        check_ms = static_ms + check_run.elapsed_ms
        yield _stage(
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
        )
        timings.append({"stage": f"check#{round_index}", "elapsed_ms": int(check_ms)})

        # 复核认定「诉求本身做不了」：重写 SQL 也无解，立即终止
        if review.unrecoverable and not review.approved:
            yield {
                "type": "error",
                "payload": {
                    "stage": "check",
                    "message": "该诉求需要写入或变更数据，只读系统无法完成，已终止。",
                    "rounds": round_index,
                    "sql": static.sql,
                    "fatal": True,
                    "total_ms": int((time.perf_counter() - total_started) * 1000),
                },
            }
            return

        if approved:
            last_sql = static.sql
            break
        feedback = _format_feedback(static.sql, review.issues)

    if not approved:
        message = "复核连续 {} 轮未通过，已终止执行。".format(config.MAX_REVIEW_ROUNDS)
        yield {
            "type": "error",
            "payload": {
                "stage": "check",
                "message": message,
                "rounds": rounds_used,
                "issues": last_review.issues if last_review else [],
                "sql": last_sql,
                "total_ms": int((time.perf_counter() - total_started) * 1000),
            },
        }
        return

    # ---------- ④ 执行 ----------
    yield _stage("execute", "running")
    try:
        result = executor.run_query(last_sql)
    except executor.QueryTimeout as exc:
        yield _stage("execute", "error", 0, message=str(exc))
        yield {"type": "error", "payload": {"stage": "execute", "message": str(exc)}}
        return
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        yield _stage("execute", "error", 0, message=message)
        yield {"type": "error", "payload": {"stage": "execute", "message": message}}
        return

    timings.append({"stage": "execute", "elapsed_ms": int(result.elapsed_ms)})
    yield _stage(
        "execute",
        "done",
        result.elapsed_ms,
        sql=last_sql,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        max_rows=config.MAX_RESULT_ROWS,
    )

    # ---------- ⑤ 归纳（流式） ----------
    yield _stage("summarize", "running")
    summarize_started = time.perf_counter()
    answer_parts: list[str] = []
    summarize_usage: dict = {}
    summarize_error: str | None = None
    async for chunk in summarize_agent.stream_summary(question, result):
        if chunk["type"] == "delta":
            answer_parts.append(chunk["text"])
            yield {"type": "delta", "stage": "summarize", "text": chunk["text"]}
        else:
            summarize_usage = chunk.get("usage") or {}
            summarize_error = chunk.get("error")
            if not answer_parts and chunk.get("text"):
                answer_parts.append(chunk["text"])

    summarize_ms = (time.perf_counter() - summarize_started) * 1000
    llm.merge_usage(usage_total, summarize_usage)
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
            yield {"type": "delta", "stage": "summarize", "text": answer[index : index + 12]}

    timings.append({"stage": "summarize", "elapsed_ms": int(summarize_ms)})
    yield _stage(
        "summarize",
        "done" if not summarize_error else "error",
        summarize_ms,
        chars=len(answer),
        usage=summarize_usage,
        model=config.SUMMARY_MODEL,
        message=summarize_error,
    )

    total_ms = (time.perf_counter() - total_started) * 1000
    yield {
        "type": "done",
        "payload": {
            "answer": answer,
            "sql": last_sql,
            "rounds": rounds_used,
            "total_ms": int(total_ms),
            "usage": usage_total,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "timings": timings,
        },
    }
