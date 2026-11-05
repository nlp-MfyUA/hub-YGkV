"""路由：POST /api/eval —— 批量评测（15 条内置测试问题）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import get_service
from ..service import LLMError
from ..schemas import EvalRequest

router = APIRouter(prefix="/api", tags=["eval"])


@router.post(
    "/eval",
    summary="批量评测",
    description=(
        "对内置测试问题批量运行工作流，返回执行成功率 / 结果正确率等指标、"
        "逐题明细（含各 stage 留痕）以及可下载的 Markdown 报告全文。"
    ),
)
def run_batch_eval(req: EvalRequest) -> dict:
    service = get_service()
    try:
        return service.run_batch_eval(ids=req.ids)
    except ValueError as exc:  # --ids 无匹配
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
