"""Streamlit UI 组件：工作流时间线、执行结果、评测报告渲染。

week13 新增：
- stream_query_with_progress：消费 SSE 事件流，实时渲染 LangGraph 逐节点进度；
- render_graph / render_state：LangGraph 图内省（Mermaid）与线程状态回查。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import ApiError, SqlAgentApiClient

STAGE_ORDER = [
    "数据库解析", "Table 选择", "SQL 生成", "SQL 校验",
    "SQL 改写", "SQL 执行", "结果汇总",
]

_STATUS_ICON = {"ok": "✅", "error": "❌", "skipped": "⏭️"}
_SQL_STAGES = {"SQL 生成", "SQL 改写"}

# LangGraph 节点名 -> 展示名（SSE node 事件用）
_NODE_LABELS = {
    "db_parser": "数据库解析",
    "table_selector": "Table 选择",
    "sql_generate": "SQL 生成",
    "sql_rewrite": "SQL 改写",
    "sql_validate": "SQL 校验",
    "sql_execute": "SQL 执行",
    "summarize": "结果汇总",
    "rewrite_router": "改写路由",
}


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


# ------------------------------------------------------------------ 流式运行
def stream_query_with_progress(
    client: SqlAgentApiClient,
    question: str,
    *,
    max_attempts: int | None = None,
    summarize: bool | None = None,
    thread_id: str | None = None,
) -> dict | None:
    """以 SSE 流式方式运行工作流，实时渲染 LangGraph 逐节点进度。

    返回最终结果 dict（与 POST /api/query 响应一致）；失败返回 None。
    连接级错误（ApiError）向上抛出，由调用方决定是否回退到非流式接口。
    """
    status = st.status("🚀 工作流执行中（LangGraph 逐节点流式推送）...",
                       expanded=True)
    for event, data in client.query_stream(
        question, max_attempts=max_attempts, summarize=summarize,
        thread_id=thread_id,
    ):
        if event == "start":
            status.write(f"🧵 LangGraph 线程已创建：`{data.get('thread_id', '')}`")
        elif event == "node":
            _render_node_event(status, data.get("node", ""), data.get("update") or {})
        elif event == "result":
            status.update(label="✅ 工作流完成", state="complete")
            return data.get("result")
        elif event == "error":
            status.update(label="❌ 工作流出错", state="error")
            st.error(data.get("detail", "未知错误"))
            return None
    status.update(label="⚠️ 流式连接中断", state="error")
    return None


def _render_node_event(status, node: str, update: dict) -> None:
    """把一个 SSE node 事件渲染进 st.status 容器。"""
    label = _NODE_LABELS.get(node, node)
    for trace in update.get("traces") or []:
        stage = trace.get("stage", label)
        icon = _STATUS_ICON.get(trace.get("status"), "❔")
        attempt = trace.get("attempt") or 0
        suffix = f"（第 {attempt} 次尝试）" if attempt > 1 else ""
        status.write(f"{icon} **{stage}**{suffix} · {_fmt_ms(trace.get('duration_ms', 0))}")
        if stage in _SQL_STAGES and trace.get("output_brief"):
            status.code(trace["output_brief"], language="sql")
        elif trace.get("status") == "error" and trace.get("detail"):
            status.caption(f"💡 {trace['detail']}")
    if update.get("tables"):
        status.caption(f"候选表：{', '.join(update['tables'])}")


# ------------------------------------------------------------------ 单条查询
def render_result(result: dict) -> None:
    """渲染一次工作流的完整结果。"""
    # -- 顶部状态横幅 ----------------------------------------------------
    usage = result.get("usage") or {}
    if result.get("success"):
        st.success(
            f"工作流成功 ｜ 尝试 {result.get('attempts', 0)} 次 ｜ "
            f"总耗时 {_fmt_ms(result.get('total_duration_ms', 0))} ｜ "
            f"token {usage.get('total_tokens', 0)}"
        )
    else:
        st.error(f"工作流失败：{result.get('error', '未知错误')}")
    if result.get("thread_id"):
        st.caption(f"🧵 LangGraph thread_id：`{result['thread_id']}`"
                   "（可在「🧭 工作流图」页回查该线程状态）")

    # -- 阶段流水线总览 ---------------------------------------------------
    st.markdown("**流程总览**")
    st.markdown(_pipeline_line(result.get("traces", [])))

    # -- 各 stage 明细 ----------------------------------------------------
    st.subheader("各阶段明细")
    for trace in result.get("traces", []):
        _render_trace(trace)

    # -- 最终 SQL ----------------------------------------------------------
    if result.get("final_sql"):
        st.subheader("最终 SQL")
        st.code(result["final_sql"], language="sql")

    # -- 执行结果 ----------------------------------------------------------
    execution = result.get("execution")
    if execution:
        count = execution.get("row_count", 0)
        truncated = "（已达行数上限，已截断）" if execution.get("truncated") else ""
        st.subheader(f"执行结果 · {count} 行 {truncated}")
        rows = execution.get("rows") or []
        if rows:
            frame = pd.DataFrame(rows, columns=execution.get("columns"))
            st.dataframe(frame, width="stretch", hide_index=True)
        else:
            st.info("查询结果为空（没有符合条件的数据）")

    # -- LLM 总结 ----------------------------------------------------------
    if result.get("summary"):
        st.subheader("LLM 总结")
        st.info(result["summary"])


def _pipeline_line(traces: list[dict]) -> str:
    last_status: dict[str, str] = {}
    for trace in traces:
        last_status[trace.get("stage", "")] = trace.get("status", "")
    parts = []
    for stage in STAGE_ORDER:
        status = last_status.get(stage)
        icon = {"ok": "🟢", "error": "🔴", "skipped": "⚪"}.get(status, "⚫")
        parts.append(f"{stage} {icon}")
    return " **→** ".join(parts)


def _render_trace(trace: dict) -> None:
    icon = _STATUS_ICON.get(trace.get("status"), "❔")
    stage = trace.get("stage", "?")
    attempt = trace.get("attempt") or 0
    suffix = f"（第 {attempt} 次尝试）" if attempt > 1 else ""
    title = f"{icon} {stage}{suffix} · {_fmt_ms(trace.get('duration_ms', 0))}"
    # 出错阶段默认展开，关键阶段默认展开，其余折叠
    expanded = trace.get("status") == "error" or stage in _SQL_STAGES | {"SQL 校验", "SQL 执行"}
    with st.expander(title, expanded=expanded):
        if trace.get("input_brief"):
            st.markdown(f"**输入**：{trace['input_brief']}")
        output = trace.get("output_brief") or ""
        if output:
            if stage in _SQL_STAGES:
                st.markdown("**输出 SQL**：")
                st.code(output, language="sql")
            else:
                st.markdown(f"**输出**：{output}")
        if trace.get("detail"):
            st.caption(f"💡 {trace['detail']}")
        usage = trace.get("usage")
        if usage and usage.get("total_tokens"):
            st.caption(
                f"token：prompt {usage.get('prompt_tokens', 0)} / "
                f"completion {usage.get('completion_tokens', 0)}"
            )


# ------------------------------------------------------------------ 批量评测
_MATCH_LABEL = {"exact": "✅ 一致", "loose": "✅ 一致(宽松)",
                "mismatch": "❌ 不一致", "gold_error": "⚠️ gold失败"}


def render_eval_report(report: dict) -> None:
    """渲染批量评测结果。"""
    metrics = report.get("metrics", {})
    total = metrics.get("total", 0)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("执行成功率", f"{metrics.get('exec_rate', 0):.1%}",
                f"{metrics.get('exec_success', 0)}/{total}")
    col2.metric("结果正确率", f"{metrics.get('correct_rate', 0):.1%}",
                f"严格 {metrics.get('exact_match', 0)} / 宽松 {metrics.get('loose_match', 0)}")
    col3.metric("平均尝试次数", f"{metrics.get('avg_attempts', 0):.2f}",
                f"重试 {metrics.get('retried', 0)} 条")
    col4.metric("总 token", metrics.get("total_tokens", 0),
                f"平均 {_fmt_ms(metrics.get('avg_duration_ms', 0))}/条")

    st.caption(
        f"模型 {report.get('provider')}/{report.get('model')} ｜ "
        f"重试上限 {report.get('max_attempts')} ｜ "
        f"时间 {report.get('started_at')} ~ {report.get('finished_at')}"
    )

    # -- 汇总表 ------------------------------------------------------------
    rows = []
    for outcome in report.get("outcomes", []):
        query = outcome.get("query", {})
        result = outcome.get("result", {})
        rows.append({
            "ID": query.get("qid"),
            "问题": query.get("question"),
            "难度": query.get("difficulty"),
            "尝试": result.get("attempts"),
            "执行": "✅" if result.get("success") else "❌",
            "结果": _MATCH_LABEL.get(outcome.get("match"), outcome.get("match")),
            "耗时": _fmt_ms(result.get("total_duration_ms", 0)),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # -- 报告下载 ----------------------------------------------------------
    markdown = report.get("markdown") or ""
    st.download_button(
        "⬇️ 下载 Markdown 评测报告",
        data=markdown,
        file_name="eval_report.md",
        mime="text/markdown",
        width="stretch",
    )
    if report.get("report_path"):
        st.caption(f"后端已同时写入：{report['report_path']}")

    # -- 逐题明细 ----------------------------------------------------------
    with st.expander("逐题明细（点击展开）"):
        for outcome in report.get("outcomes", []):
            query = outcome.get("query", {})
            result = outcome.get("result", {})
            header = (
                f"{query.get('qid')} · {query.get('question')} ｜ "
                f"尝试 {result.get('attempts')} 次 ｜ "
                f"{_MATCH_LABEL.get(outcome.get('match'), '')}"
            )
            with st.expander(header):
                st.markdown(f"**考察点**：{query.get('category')}（{query.get('difficulty')}）")
                st.markdown(f"**比对结果**：{outcome.get('match_detail', '')}")
                if result.get("final_sql"):
                    st.markdown("**工作流 SQL**：")
                    st.code(result["final_sql"], language="sql")
                if result.get("summary"):
                    st.caption(f"LLM 总结：{result['summary']}")
                if result.get("error"):
                    st.warning(result["error"])


# ------------------------------------------------------------------ 数据库结构
def render_schema(schema: dict) -> None:
    for table in schema.get("tables", []):
        title = f"📋 {table['name']}（{table.get('comment', '')}，{table.get('row_count', 0)} 行）"
        with st.expander(title, expanded=False):
            columns = pd.DataFrame([
                {
                    "列名": c["name"],
                    "类型": c["type"],
                    "主键": "🔑" if c.get("primary_key") else "",
                    "非空": "✔" if c.get("not_null") else "",
                    "注释": c.get("comment", ""),
                    "取值/枚举": "、".join((c.get("distinct_values") or [])[:12]),
                }
                for c in table.get("columns", [])
            ])
            st.dataframe(columns, width="stretch", hide_index=True)
            foreign_keys = table.get("foreign_keys") or []
            if foreign_keys:
                st.caption("外键：" + "，".join(
                    f"{fk['column']} → {fk['ref_table']}.{fk['ref_column']}"
                    for fk in foreign_keys
                ))
            st.code(table.get("ddl", ""), language="sql")


# ------------------------------------------------------------------ 工作流图（week13）
def render_graph(graph: dict) -> None:
    """渲染 LangGraph 状态机图（Mermaid 源码 + 节点说明）。"""
    st.markdown(
        "工作流由 **LangGraph StateGraph** 编排：八个节点（七个 stage + 改写路由），"
        "条件边表达「校验失败 / 执行报错 → 改写 → 重试」回路。"
        "下图由后端 `/api/graph` 实时导出（图即代码）。"
    )
    mermaid = graph.get("mermaid", "")
    st.code(mermaid, language="mermaid")
    st.caption(
        "提示：把上面的 Mermaid 源码粘贴到支持 Mermaid 的渲染器"
        "（如 GitHub Markdown / mermaid.live）即可看到图形。"
    )
    with st.expander("节点清单"):
        for node in graph.get("nodes", []):
            st.markdown(f"- `{node}` → {_NODE_LABELS.get(node, node)}")


def render_state(snapshot: dict | None, thread_id: str) -> None:
    """渲染某次运行（thread）的状态回查结果。"""
    if snapshot is None:
        st.warning(f"未找到线程 `{thread_id}` 的状态（可能未运行过，或进程已重启且 "
                   "checkpoint 为 memory 模式）。")
        return
    st.caption(f"来源：{snapshot.get('source')}")
    if "result" in snapshot:
        result = snapshot["result"]
        st.markdown(f"- 成功：**{'是' if result.get('success') else '否'}**")
        st.markdown(f"- 尝试次数：{result.get('attempts', 0)}")
        st.markdown(f"- 留痕条数：{len(result.get('traces') or [])}")
        if result.get("final_sql"):
            st.markdown("**最终 SQL**")
            st.code(result["final_sql"], language="sql")
        if result.get("summary"):
            st.info(result["summary"])
        if result.get("error"):
            st.warning(result["error"])
    else:
        state = snapshot.get("state") or {}
        st.markdown(f"- 成功：**{'是' if state.get('success') else '否'}**")
        st.markdown(f"- 尝试次数：{state.get('attempt', 0)}")
        st.markdown(f"- 留痕条数：{len(state.get('traces') or [])}")
        if state.get("sql"):
            st.markdown("**最终 SQL**")
            st.code(state["sql"], language="sql")
