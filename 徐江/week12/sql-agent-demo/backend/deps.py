"""服务单例依赖（供路由层获取 WorkflowService）。"""
from __future__ import annotations

from .service import WorkflowService, get_service, init_service

__all__ = ["WorkflowService", "get_service", "init_service"]
