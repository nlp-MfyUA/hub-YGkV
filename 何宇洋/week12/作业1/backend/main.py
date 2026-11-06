import os
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .risk import classify, demo_observation
from .service import MAX_BYTES, prepare_image, recognize

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="楼道安全巡检 Demo", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/config")
def config():
    return {"paid_enabled": os.getenv("ALLOW_PAID_API") == "1",
            "key_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"), "max_upload_mb": 10}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), mode: Literal["demo", "live"] = Form("demo"),
                  preset: Literal["high", "medium", "low", "none", "not_corridor"] = Form("high")):
    started = time.monotonic()
    if mode == "live" and os.getenv("ALLOW_PAID_API") != "1":
        await file.close()
        raise HTTPException(403, "真实调用尚未开启。请手动设置 ALLOW_PAID_API=1 并重启后端。")
    try:
        data = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    image = await run_in_threadpool(prepare_image, data)
    observation = demo_observation(preset) if mode == "demo" else await recognize(image)
    return {"id": uuid4().hex[:12], "mode": mode,
            "model": "固定示例（未识别图片）" if mode == "demo" else os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            **classify(observation), "observation": observation.model_dump()}
