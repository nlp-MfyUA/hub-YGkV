"""路由：GET /api/graph —— LangGraph 状态机的 Mermaid 图（week13 新增）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import get_service
from ..service import LLMError

router = APIRouter(prefix="/api", tags=["graph"])


@router.get(
    "/graph",
    summary="获取工作流状态机图（Mermaid）",
    description=(
        "返回 LangGraph 状态机的 Mermaid 源码（图即代码）："
        "八个节点（七个 stage + 改写路由）与改写重试回边一目了然，"
        "可粘贴到任何支持 Mermaid 的渲染器查看。"
    ),
)
def get_graph() -> dict:
    try:
        return get_service().graph_mermaid()
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
