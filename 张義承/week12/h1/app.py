"""楼道消防安全隐患排查 Web 应用（FastAPI 入口）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from analyzer import (
    AnalyzeError,
    analyze_image,
    api_key,
    max_image_bytes,
    model_name,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

app = FastAPI(title="楼道消防安全隐患排查", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": model_name(),
        "key_configured": bool(api_key()),
        "max_image_mb": max_image_bytes() // (1024 * 1024),
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)) -> dict[str, object]:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="仅支持 JPG、PNG、WebP 格式的图片。",
        )

    data = await file.read(max_image_bytes() + 1)
    if len(data) > max_image_bytes():
        raise HTTPException(
            status_code=400,
            detail=f"图片超过 {max_image_bytes() // (1024 * 1024)}MB 限制，请压缩后重试。",
        )

    try:
        return await analyze_image(data)
    except AnalyzeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        await file.close()
