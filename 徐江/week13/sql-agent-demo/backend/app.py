"""FastAPI 应用工厂与启动入口。

启动（在项目根目录执行）：
    uvicorn backend.app:app --port 8000
    LLM_PROVIDER=mock uvicorn backend.app:app --port 8000    # 离线 mock 模式

交互式 API 文档：http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 保证 `import backend.*` 与 `import sql_agent` 都能找到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .deps import init_service
from .routers import eval as eval_router
from .routers import graph as graph_router
from .routers import health as health_router
from .routers import query as query_router
from .routers import schema as schema_router
from .routers import state as state_router

DESCRIPTION = """
固定流程的 SQL Agent 工作流 API（week13 · LangGraph 框架版）。

工作流：数据库解析 → Table 选择 → SQL 生成 → SQL 校验 → SQL 改写（失败重试）→ SQL 执行 → 结果汇总，
由 LangGraph StateGraph 编排（checkpointer 持久化 + thread_id 状态回查）。

* `POST /api/query`        运行一次工作流，返回全部 stage 留痕
* `POST /api/query/stream` 流式运行（SSE 逐节点推送进度）
* `GET  /api/schema`       查看数据库结构
* `POST /api/eval`         批量评测（内置 15 条测试问题）
* `GET  /api/graph`        状态机 Mermaid 图（图即代码）
* `GET  /api/state/{id}`   回查某次运行的状态快照
* `GET  /api/health`       服务与模型状态
"""


def create_app(config_path: str | None = None) -> FastAPI:
    app = FastAPI(
        title="SQL Agent Workflow API",
        description=DESCRIPTION,
        version="4.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],      # 演示项目放开跨域；生产环境应收敛到前端域名
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 服务初始化失败（配置缺失 / 未填 Key）不阻塞启动，由 /api/health 如实反映
    init_service(config_path or os.environ.get("SQL_AGENT_CONFIG"))

    app.include_router(health_router.router)
    app.include_router(query_router.router)
    app.include_router(schema_router.router)
    app.include_router(eval_router.router)
    app.include_router(graph_router.router)
    app.include_router(state_router.router)
    return app


app = create_app()
