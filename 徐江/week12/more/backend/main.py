"""FastAPI 主应用（技术设计文档 §12）。

端点：
- POST /api/analyze  图片上传 → 五级风险识别（F-05 ~ F-08 全链路）
- GET  /api/health   服务与通道状态（F-09）
- GET  /api/config   脱敏配置（F-09）
- GET  /             静态托管 frontend/（移动端 Web）

统一约定：
- 错误响应恒为 {"request_id", "error_code", "detail"}，错误码矩阵见 errors.py；
- 日志只记元数据（F-10），不记录图片内容 / Base64 / API Key。
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .arbiter import arbitrate
from .config import get_settings
from .errors import (
    ApiError,
    InvalidEnumError,
    ModelOutputUnparseableError,
    ProviderNotConfiguredError,
    UnauthorizedError,
)
from .prompt import SYSTEM_PROMPT, USER_TEXT
from .providers import build_provider
from .providers.base import RawResult, VisionProvider
from .schemas import AnalyzeResponse, ConfigResponse, ErrorResponse, HealthResponse, ModelOutput
from .utils import encode_image, parse_model_json, validate_image

logger = logging.getLogger("corridor-risk")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动钩子：校验必填环境变量，缺失则记 ERROR 并拒绝启动（F-09）。"""
    settings = get_settings()
    missing: list[str] = []
    if settings.vision_provider not in ("deepseek", "qwen"):
        missing.append(f"VISION_PROVIDER（当前值 {settings.vision_provider!r} 非法）")
    if not settings.active_api_key:
        missing.append(f"{settings.vision_provider.upper()}_API_KEY")
    if not settings.active_base_url:
        missing.append(f"{settings.vision_provider.upper()}_BASE_URL")
    if missing:
        for name in missing:
            logger.error("缺少必填配置 %s（请在 .env 中填写，参考 .env.example）", name)
        raise RuntimeError(f"启动失败：缺少必填配置 {missing}")

    app.state.provider = build_provider(settings)
    logger.info("provider=%s model=%s 启动就绪", settings.vision_provider, settings.active_model)
    yield
    app.state.provider = None


app = FastAPI(title="楼道消防安全多模态识别 Demo", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------- 错误处理


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:8]
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(request_id=rid, error_code=exc.error_code,
                              detail=exc.detail).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:8]
    # 静态托管等场景的 404/405 保持原生语义，不包装成 500
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logger.exception("未处理异常 rid=%s", rid)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(request_id=rid, error_code="internal_error",
                              detail="服务内部错误，请稍后重试").model_dump(),
    )


# ---------------------------------------------------------------- 内部逻辑


def get_provider() -> VisionProvider:
    provider = getattr(app.state, "provider", None)
    if provider is None:
        raise ProviderNotConfiguredError("视觉通道未初始化，请检查 .env 配置后重启服务")
    return provider


async def call_with_retry(provider: VisionProvider, image_b64: str, mime: str,
                          max_retries: int) -> RawResult:
    """调用模型；仅对可重试错误（网络错误 / 5xx）在预算内重试（F-07）。"""
    attempt = 0
    while True:
        try:
            return await provider.analyze(image_b64, SYSTEM_PROMPT, USER_TEXT, mime=mime)
        except ApiError as exc:
            if not exc.retryable or attempt >= max_retries:
                raise
            attempt += 1
            logger.warning("模型调用失败（%s），重试 %d/%d", exc.error_code, attempt, max_retries)


def parse_model_output(text: str) -> ModelOutput:
    """JSON 容错解析 + Pydantic 校验（F-07）。

    枚举字段（scene_type / risk_level / confidence / signals.level）越界
    → invalid_enum；其余结构问题 → model_output_unparseable。
    """
    data = parse_model_json(text)
    try:
        return ModelOutput(**data)
    except ValidationError as exc:
        bad = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(根)'}={e['input']!r}" for e in exc.errors()
        )
        # 值越界（Literal 不匹配）→ invalid_enum；字段缺失/类型不符 → model_output_unparseable
        is_enum = any(e.get("type") == "literal_error" for e in exc.errors())
        err_cls = InvalidEnumError if is_enum else ModelOutputUnparseableError
        raise err_cls(f"模型返回字段不合法：{bad}") from exc


# ---------------------------------------------------------------- 端点


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request, image: Annotated[UploadFile, File(...)]) -> AnalyzeResponse:
    rid = uuid.uuid4().hex[:8]
    request.state.request_id = rid
    settings = get_settings()

    if settings.demo_token and request.headers.get("X-Demo-Token") != settings.demo_token:
        raise UnauthorizedError("演示令牌校验失败，请在请求头携带正确的 X-Demo-Token")

    t0 = time.perf_counter()
    data = await image.read()
    filename = image.filename or "unnamed"
    content_type = image.content_type or ""

    # F-05 校验 → F-06/F-07 Base64 + 模型调用 + 解析 → F-08 裁决
    width, height = validate_image(
        data, content_type,
        max_mb=settings.max_image_mb, min_side=settings.min_image_side,
    )
    provider = get_provider()
    raw = await call_with_retry(provider, encode_image(data), _mime_of(content_type, data),
                                settings.max_retries)
    model_out = parse_model_output(raw.text)
    final_level, override = arbitrate(model_out)

    # F-10 请求日志：只记元数据，不记图片内容 / Base64 / Key
    logger.info(
        "analyze rid=%s file=%s size=%d dims=%dx%d provider=%s model=%s "
        "latency=%d level=%s override=%s parse_ok=true",
        rid, filename, len(data), width, height, raw.provider, raw.model,
        raw.latency_ms, final_level, override,
    )

    return AnalyzeResponse(
        request_id=rid,
        risk_level=final_level,
        confidence=model_out.confidence,
        evidence=model_out.evidence,
        scene_type=model_out.scene_type,
        signals=model_out.signals,
        arbiter_override=override,
        provider=raw.provider,
        model=raw.model,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )


def _mime_of(content_type: str, data: bytes) -> str:
    """data URL 用的 MIME：优先客户端声明，缺失时按 Pillow 嗅探结果。"""
    from PIL import Image
    import io

    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in ("image/jpeg", "image/png", "image/webp"):
        return ct
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
        return {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(fmt, "image/jpeg")
    except Exception:
        return "image/jpeg"


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    configured = bool(settings.active_api_key and settings.active_base_url)
    return HealthResponse(
        status="ok" if configured else "degraded",
        provider=settings.vision_provider,
        model=settings.active_model,
        base_url_configured=bool(settings.active_base_url),
        api_key_configured=bool(settings.active_api_key),
    )


@app.get("/api/config", response_model=ConfigResponse)
async def config() -> ConfigResponse:
    settings = get_settings()
    return ConfigResponse(
        provider=settings.vision_provider,
        model=settings.active_model,
        max_image_mb=settings.max_image_mb,
        timeout_s=settings.timeout_s,
    )


# ---------------------------------------------------------------- 静态托管

if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    logger.warning("frontend 目录不存在（%s），跳过静态托管", FRONTEND_DIR)
