"""路由：GET /api/schema —— 数据库结构（供前端「数据库结构」页展示）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import get_service
from ..service import LLMError

router = APIRouter(prefix="/api", tags=["schema"])


@router.get("/schema", summary="获取数据库 schema")
def get_schema() -> dict:
    try:
        return get_service().schema()
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
