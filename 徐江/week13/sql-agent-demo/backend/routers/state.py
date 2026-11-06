"""路由：GET /api/state/{thread_id} —— 回查某次运行的状态（week13 新增）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import get_service

router = APIRouter(prefix="/api", tags=["state"])


@router.get(
    "/state/{thread_id}",
    summary="回查 LangGraph 线程状态",
    description=(
        "按 thread_id 回查一次工作流运行的状态快照（来自 checkpointer / "
        "进程内注册表）：包含最终 SQL、七阶段留痕、执行结果等。"
        "thread_id 由 POST /api/query（或 /api/query/stream）的响应给出。"
    ),
)
def get_state(thread_id: str) -> dict:
    snapshot = get_service().state_snapshot(thread_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"未找到线程 {thread_id!r} 的状态")
    return snapshot
