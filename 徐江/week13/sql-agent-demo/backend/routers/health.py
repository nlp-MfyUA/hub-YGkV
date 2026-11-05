"""路由：GET /api/health —— 服务与模型状态探测。"""
from __future__ import annotations

from fastapi import APIRouter

from ..deps import get_service

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", summary="健康检查 / 当前模型信息")
def health() -> dict:
    return get_service().health()
