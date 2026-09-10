"""
FastAPI 应用入口

深度研究助手 RESTful API 服务
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import research
from app.config import get_settings
from app.utils.logger import setup_logging


# 初始化日志
setup_logging()

# 创建 FastAPI 应用
app = FastAPI(
    title="深度研究助手 API",
    description="基于 Agent + Embedding 的自动化深度研究报告生成服务",
    version="0.1.0",
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(
    research.router,
    prefix="/api/v1",
    tags=["research"],
)


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    settings = get_settings()
    settings.ensure_directories()


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    pass


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "深度研究助手 API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}