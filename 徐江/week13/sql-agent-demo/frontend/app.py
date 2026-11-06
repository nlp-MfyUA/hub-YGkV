"""Streamlit 前端入口。

启动（在项目根目录执行）：
    streamlit run frontend/app.py

本前端不 import sql_agent / eval 等核心包，只通过 HTTP 调用 FastAPI 后端，
是前后端分离架构中的纯客户端。默认连接 http://127.0.0.1:8000，
可在左侧侧边栏修改。

week13 起（LangGraph 框架版）：
- 「单条查询」页支持 SSE 流式运行，实时展示 LangGraph 逐节点进度；
- 新增「工作流图」页：状态机 Mermaid 图 + thread_id 状态回查。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 保证 `import api_client / components` 可用（Streamlit 会把脚本目录加入 sys.path，
# 这里再显式兜底一次）
FRONTEND_DIR = Path(__file__).resolve().parent
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

import streamlit as st

from api_client import ApiError, SqlAgentApiClient
import components

# ------------------------------------------------------------------ 页面配置
st.set_page_config(page_title="SQL Agent 工作流", page_icon="🤖", layout="wide")

# ------------------------------------------------------------------ 侧边栏
with st.sidebar:
    st.header("🔌 后端连接")
    base_url = st.text_input("后端地址", value="http://127.0.0.1:8000")
    client = SqlAgentApiClient(base_url)

    if st.button("检查连接", width="stretch"):
        try:
            health = client.health()
            if health.get("status") == "ok":
                st.success(f"已连接 ｜ 模型 {health.get('model')}（{health.get('provider')}）")
                st.caption(
                    f"数据库：{health.get('db_path')}\n\n"
                    f"{health.get('table_count')} 张表 ｜ 行数上限 {health.get('row_limit')} ｜ "
                    f"默认重试 {health.get('max_attempts')} 次"
                )
            else:
                st.error(f"后端未就绪：{health.get('detail', '未知状态')}")
                st.caption("请检查 config.local.yaml 的 llm.api_key，"
                           "或使用 LLM_PROVIDER=mock 启动后端。")
        except ApiError as exc:
            st.error(str(exc))

    st.divider()
    st.header("⚙️ 运行参数")
    max_attempts = st.slider("工作流重试上限", min_value=1, max_value=5, value=3)
    summarize = st.checkbox("执行「结果汇总」阶段（LLM 总结）", value=True)
    use_stream = st.checkbox(
        "SSE 流式运行（实时查看 LangGraph 逐节点进度）", value=True)

    st.divider()
    st.header("🧵 最近一次运行")
    last_thread = st.session_state.get("last_thread_id")
    if last_thread:
        st.caption(f"thread_id：`{last_thread}`")
        if st.button("回查该线程状态", width="stretch"):
            try:
                snapshot = client.state(last_thread)
            except ApiError as exc:
                st.error(str(exc))
            else:
                if snapshot is None:
                    st.warning("未找到该线程状态")
                else:
                    result = snapshot.get("result") or snapshot.get("state") or {}
                    st.markdown(f"- 成功：**{'是' if result.get('success') else '否'}**"
                                f"｜尝试 {result.get('attempts', 0)} 次"
                                f"｜留痕 {len(result.get('traces') or [])} 条")
                    if result.get("final_sql"):
                        st.code(result["final_sql"], language="sql")
    else:
        st.caption("运行一次工作流后，可在这里按 thread_id 回查 LangGraph 状态。")

    st.divider()
    st.caption(
        "前后端分离架构：本页面是纯前端，只通过 HTTP 调用 FastAPI 后端；"
        "核心工作流（sql_agent/）运行在后端进程内，由 LangGraph 编排。"
    )

# ------------------------------------------------------------------ 主区域
st.title("🤖 SQL Agent 工作流")
st.caption("数据库解析 → Table 选择 → SQL 生成 → SQL 校验 → SQL 改写（按需）→ SQL 执行 → 结果汇总"
           " ｜ LangGraph 状态机编排（week13）")

tab_query, tab_eval, tab_schema, tab_graph = st.tabs(
    ["💬 单条查询", "📊 批量评测", "🗄️ 数据库结构", "🧭 工作流图"])

# -- Tab 1 · 单条查询 --------------------------------------------------------
with tab_query:
    question = st.text_input(
        "输入你的自然语言问题",
        value="每个城市有多少用户？按用户数从多到低排序",
    )
    col_run, col_hint = st.columns([1, 3])
    with col_run:
        run_clicked = st.button("🚀 运行工作流", type="primary", width="stretch")
    with col_hint:
        st.caption("试试「销量前 10 的商品」「从来没有下过单的用户」「2024 年每个月的订单量」")

    if run_clicked:
        if not question.strip():
            st.warning("请输入问题后再运行。")
        else:
            result = None
            stream_done = False
            if use_stream:
                # 流式：实时展示逐节点进度；连接级失败（ApiError）才回退非流式
                try:
                    result = components.stream_query_with_progress(
                        client, question,
                        max_attempts=max_attempts, summarize=summarize,
                    )
                    stream_done = True  # 流式通道已完整走完（含 error 事件）
                except ApiError as exc:
                    st.warning(f"流式连接失败（{exc}），已回退到普通模式。")
            if not stream_done:
                with st.spinner("工作流执行中（包含多次 LLM 调用，请稍候）..."):
                    try:
                        result = client.query(
                            question, max_attempts=max_attempts, summarize=summarize
                        )
                    except ApiError as exc:
                        st.error(str(exc))
                        st.stop()
            if result is not None:
                if result.get("thread_id"):
                    st.session_state["last_thread_id"] = result["thread_id"]
                components.render_result(result)

# -- Tab 2 · 批量评测 --------------------------------------------------------
with tab_eval:
    st.subheader("批量评测")
    st.caption("对内置的 15 条测试问题（简单 / 中等 / 复杂）批量运行工作流，"
               "统计执行成功率与结果正确率，并生成可下载的 Markdown 报告。")
    ids = st.text_input("问题子集（可选）", placeholder="例如 1,5,8 或 1-5；留空跑全部 15 条")
    if st.button("📊 开始评测", type="primary"):
        with st.spinner("批量评测运行中，每条问题包含多次 LLM 调用，请耐心等待..."):
            try:
                report = client.eval(ids=ids.strip() or None)
            except ApiError as exc:
                st.error(str(exc))
                st.stop()
        components.render_eval_report(report)

# -- Tab 3 · 数据库结构 ------------------------------------------------------
with tab_schema:
    st.subheader("数据库结构")
    st.caption("来自后端「数据库解析」阶段的实时 schema。")
    # 按需加载：页面初始渲染不强依赖后端连接，加载结果在会话内保持
    load_clicked = st.button("🔄 加载 / 刷新数据库结构", width="stretch")
    if load_clicked or st.session_state.get("schema_loaded"):
        st.session_state["schema_loaded"] = True
        try:
            schema = client.schema()
        except ApiError as exc:
            st.error(str(exc))
        else:
            components.render_schema(schema)
    else:
        st.info("点击上方按钮，从后端加载数据库结构。")

# -- Tab 4 · 工作流图（week13 新增）------------------------------------------
with tab_graph:
    st.subheader("工作流状态机（LangGraph）")
    try:
        graph = client.graph()
    except ApiError as exc:
        st.error(str(exc))
    else:
        components.render_graph(graph)

    st.divider()
    st.subheader("线程状态回查")
    st.caption("每次运行工作流都会得到一个 thread_id（见「单条查询」结果或侧边栏），"
               "在此输入即可回查该次运行在 checkpointer 中的状态快照。")
    thread_input = st.text_input(
        "thread_id", value=st.session_state.get("last_thread_id", ""),
        placeholder="粘贴某次运行的 thread_id")
    if st.button("🔍 回查状态", width="stretch"):
        tid = thread_input.strip()
        if not tid:
            st.warning("请输入 thread_id。")
        else:
            try:
                snapshot = client.state(tid)
            except ApiError as exc:
                st.error(str(exc))
            else:
                components.render_state(snapshot, tid)
