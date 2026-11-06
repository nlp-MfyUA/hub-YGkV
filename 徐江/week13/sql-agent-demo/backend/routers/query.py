"""路由：POST /api/query —— 执行一次 SQL Agent 工作流（含 SSE 流式变体）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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
        "week13 起附带 thread_id（LangGraph 线程标识），可用于回查状态。"
    ),
)
def run_query(req: QueryRequest) -> dict:
    service = get_service()
    try:
        return service.query(
            req.question,
            max_attempts=req.max_attempts,
            summarize=req.summarize,
            thread_id=req.thread_id,
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/query/stream",
    summary="流式运行工作流（SSE）",
    description=(
        "与 /api/query 等价的流式版本：基于 LangGraph 的 "
        "stream(stream_mode=\"updates\") 逐节点推送事件，"
        "事件类型 start / node / result / error（text/event-stream）。"
        "最终 result 事件的载荷与 /api/query 的响应体完全一致。"
    ),
)
def run_query_stream(req: QueryRequest) -> StreamingResponse:
    service = get_service()
    try:
        events = service.stream_query(
            req.question,
            max_attempts=req.max_attempts,
            summarize=req.summarize,
            thread_id=req.thread_id,
        )
    except LLMError as exc:
        # 流式响应一旦开始就无法再改状态码，因此在开流前同步校验
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def _sse():
        for event in events:
            name = event["event"]
            data = json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {name}\ndata: {data}\n\n"

    # Starlette 会把同步生成器自动放进线程池执行，不会阻塞事件循环
    return StreamingResponse(_sse(), media_type="text/event-stream")
