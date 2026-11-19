"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chat import router as chat_router
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.core.config import get_settings
from app.core.db import init_db
from app.core.logging import setup_logging
from app.services.kafka_producer import start_producer, stop_producer

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.ensure_dirs()
    init_db()
    await start_producer()
    yield
    await stop_producer()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(chat_router)


@app.get("/")
def index():
    return {"name": settings.app_name, "docs": "/docs", "health": "/api/health"}
