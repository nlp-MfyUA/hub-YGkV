"""路由：POST /api/query —— 执行一次 SQL Agent 工作流。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import get_service
from ..service import LLMError  # service 导入时已完成 sys.path 引导
from ..schemas import QueryRequest

router = APIRouter(prefix="/api", tags=["query"])


@router.post(
    "/query",
    summary="运行工作流",
    description=(
        "输入自然语言问题，依次经过 数据库解析 → Table 选择 → SQL 生成 → "
        "SQL 校验 → SQL 改写(按需) → SQL 执行 → 结果汇总，"
        "返回每个 stage 的输入输出留痕、最终 SQL、执行结果与 LLM 总结。"
    ),
)
def run_query(req: QueryRequest) -> dict:
    service = get_service()
    try:
        return service.query(
            req.question,
            max_attempts=req.max_attempts,
            summarize=req.summarize,
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
