"""运行入口：python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"""
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.imaging import MAX_FILE_BYTES, to_jpeg
from backend.risk import make_report, validate_facts
from backend.vision import VisionAPIError, inspect_image, provider_status

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="楼道消防安全隐患智能识别系统", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/status")
async def status():
    return {"models": provider_status(), "mode": "real_api"}


@app.post("/api/analyze")
async def analyze(
    image: UploadFile = File(...),
    provider: Literal["deepseek", "qwen"] = Form("deepseek"),
):
    raw = await image.read(MAX_FILE_BYTES + 1)
    await image.close()
    jpeg = to_jpeg(raw)
    try:
        model_text, model = await inspect_image(jpeg, provider)
        facts = validate_facts(model_text)
    except VisionAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"模型格式不正确：{exc}") from exc
    return make_report(facts, provider, model)
