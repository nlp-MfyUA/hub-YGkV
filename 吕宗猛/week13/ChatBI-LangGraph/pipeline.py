"""流程编排入口：消费 LangGraph 图的 custom 事件流。

维持与 week12 一致的 `run_pipeline(question)` 异步迭代器签名（smoke.py 与
main.py 的对接方式不变）；week13 新增可选 `history` 参数承载对话历史，
用于支持追问（详见 graph.py 与 agent/generate_agent.py）。
"""

from __future__ import annotations

import time
from typing import AsyncIterator

from agent import check_agent, generate_agent
from graph import build_graph

_graph = None


def _get_graph():
    """图拓扑是静态的，整个进程构建一次；每请求状态走独立的 state。"""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_pipeline(
    question: str,
    history: list[dict] | None = None,
) -> AsyncIterator[dict]:
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "payload": {"stage": "input", "message": "问题不能为空"}}
        return

    state = {
        "question": question,
        "history": list(history or []),
        "started_at": time.perf_counter(),
        # Agent 实例按请求创建：收口工具写入的 store 容器必须请求间隔离
        "generator": generate_agent.build_agent(),
        "reviewer": check_agent.build_agent(),
        "usage_total": {},
        "timings": [],
    }

    async for chunk in _get_graph().astream(state, stream_mode="custom"):
        yield chunk
