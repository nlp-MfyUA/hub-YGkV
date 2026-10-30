"""作业一：楼道消防隐患识别 —— FastAPI 后端。

前后端一体：同一个进程既提供 /api/analyze，也托管 static/ 下的网页。
运行：
    python app.py                       # 打开 http://127.0.0.1:8000
    python app.py --host 0.0.0.0        # 同一局域网的手机也能访问
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from image_utils import ImageError, prepare_image  # noqa: E402
from schemas import AnalysisMeta, AnalysisResponse, HealthResponse  # noqa: E402
from vision import VisionClient, VisionError, describe_error  # noqa: E402

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("corridor-risk")

MAX_UPLOAD_MB = 10
STATIC_DIR = BASE_DIR / "static"

# VisionClient 在启动时创建；没有配置 Key 时保留错误信息，接口再给出明确提示
vision_client: VisionClient | None = None
vision_error: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global vision_client, vision_error
    try:
        vision_client = VisionClient()
        logger.info("视觉模型：%s（%s）", vision_client.model, vision_client.base_url)
    except Exception as exc:  # 缺 Key 不阻止服务启动，方便先打开页面
        vision_error = describe_error(exc)
        logger.warning("视觉模型未就绪：%s", vision_error)
    yield
    vision_client = None


app = FastAPI(title="楼道消防隐患识别", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        ok=vision_client is not None,
        model=vision_client.model if vision_client else "未配置",
        provider=vision_client.provider if vision_client else "未配置",
        max_upload_mb=MAX_UPLOAD_MB,
    )


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze(file: UploadFile = File(...)) -> AnalysisResponse:
    if vision_client is None:
        raise HTTPException(status_code=503, detail=vision_error or "视觉模型未配置")

    raw = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="没有收到图片文件")

    try:
        jpeg_bytes, mime, size_text = await run_in_threadpool(prepare_image, raw)
    except ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    logger.info("收到识别请求 %s：%s，%dKB，%s", request_id, file.filename, len(raw) // 1024, size_text)

    try:
        assessment, repairs = await run_in_threadpool(
            vision_client.analyze, jpeg_bytes, mime
        )
    except VisionError as exc:
        logger.error("识别失败 %s：%s", request_id, exc)
        raise HTTPException(status_code=502, detail=describe_error(exc)) from exc
    except Exception as exc:  # 兜底，避免异常细节直接暴露给前端
        logger.exception("识别异常 %s", request_id)
        raise HTTPException(status_code=500, detail=f"服务内部错误：{exc}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "识别完成 %s：%s（%d 分），耗时 %dms%s",
        request_id,
        assessment.risk_level.value,
        assessment.risk_score,
        latency_ms,
        "，触发过一次修复" if repairs else "",
    )

    return AnalysisResponse(
        data=assessment,
        meta=AnalysisMeta(
            model=vision_client.model,
            provider=vision_client.provider,
            latency_ms=latency_ms,
            image_bytes=len(jpeg_bytes),
            image_size=size_text,
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            request_id=request_id,
        ),
    )


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException) -> JSONResponse:
    """统一错误结构，前端只需要读 detail。"""
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "detail": exc.detail})


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="楼道消防隐患识别（多模态）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，手机访问时用 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发模式，改代码自动重启")
    args = parser.parse_args()

    print(f"\n  楼道消防隐患识别  ->  http://127.0.0.1:{args.port}\n")
    uvicorn.run("app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
