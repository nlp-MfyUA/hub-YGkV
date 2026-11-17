"""FastAPI 入口。

启动：python -m app.main
或者：uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app import db, image_utils  # noqa: E402
from app.analyzer import AnalysisError, analyze, analyze_with_boxes  # noqa: E402
from app.llm import (  # noqa: E402
    DEFAULT_PROVIDER,
    MAX_UPLOAD_MB,
    RISK_COLORS,
    RISK_LABELS_CN,
    ProviderError,
    build_model,
    provider_status,
)
from app.schemas import AnalyzeResponse  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
LOGGER = logging.getLogger("app.main")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    LOGGER.info("已配置供应商: %s", provider_status())
    yield


app = FastAPI(title="楼道消防安全风险识别", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------- 静态资源
app.mount("/media/uploads", StaticFiles(directory="data/uploads", check_dir=False), name="uploads")
app.mount(
    "/media/annotated", StaticFiles(directory="data/annotated", check_dir=False), name="annotated"
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------- 业务接口
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "default_provider": DEFAULT_PROVIDER,
        "providers": provider_status(),
        "max_upload_mb": MAX_UPLOAD_MB,
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_api(
    file: UploadFile = File(...),
    provider: str = Form(default=DEFAULT_PROVIDER),
    annotate: bool = Form(default=False),
) -> AnalyzeResponse:
    request_id = uuid.uuid4().hex[:12]

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="上传文件为空")
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {MAX_UPLOAD_MB}MB")

    # 先确认图片能解码，再落盘，避免脏文件
    try:
        image_utils.load_image(raw)
        image_url, _ = image_utils.save_upload(raw)
    except image_utils.ImageProcessError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    t0 = time.perf_counter()
    annotated_url: str | None = None
    try:
        if annotate:
            result, latency, boxes = analyze_with_boxes(raw, provider)
            annotated_url = image_utils.save_annotated(image_url, boxes)
        else:
            result, latency = analyze(raw, provider)
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AnalysisError as exc:
        LOGGER.warning("分析失败 %s: %s", request_id, exc)
        total_ms = int((time.perf_counter() - t0) * 1000)
        db.save_record(
            request_id=request_id,
            provider=provider,
            model="-",
            risk_level=None,
            risk_score=None,
            is_hallway=None,
            image_url=image_url,
            latency_ms=total_ms,
            reason=str(exc),
        )
        return AnalyzeResponse(
            status="invalid_output",
            request_id=request_id,
            provider=provider,
            model="-",
            latency_ms=total_ms,
            image_url=image_url,
            message=str(exc),
        )

    total_ms = int((time.perf_counter() - t0) * 1000)
    model_name = getattr(build_model(provider), "model_name", "-")

    db.save_record(
        request_id=request_id,
        provider=provider,
        model=model_name,
        risk_level=result.risk_level,
        risk_score=result.risk_score,
        is_hallway=result.is_hallway,
        image_url=image_url,
        latency_ms=total_ms,
        reason=result.reason,
    )

    # 分数落在分档临界区间 -> 提示人工复核
    need_review = result.risk_level in ("low", "medium") and 40 <= result.risk_score <= 60

    return AnalyzeResponse(
        status="ok",
        request_id=request_id,
        provider=provider,
        model=model_name,
        latency_ms=total_ms,
        risk_level=result.risk_level,
        risk_level_cn=RISK_LABELS_CN.get(result.risk_level, result.risk_level),
        risk_color=RISK_COLORS.get(result.risk_level),
        risk_score=result.risk_score,
        is_hallway=result.is_hallway,
        hazards=result.hazards,
        observations=result.observations,
        reason=result.reason,
        advice=result.advice,
        need_review=need_review,
        image_url=image_url,
        annotated_url=annotated_url,
    )


@app.get("/api/history")
def history(limit: int = 20) -> dict:
    limit = max(1, min(limit, 200))
    return {"items": db.list_records(limit), "stats": db.stats()}


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
