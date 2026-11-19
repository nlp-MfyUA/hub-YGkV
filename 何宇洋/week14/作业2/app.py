from contextlib import asynccontextmanager
import logging
import os
import shutil
from threading import Event, Thread
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
from PIL import Image

from chat import answer, image_part
from parsing import IMAGE_SUFFIXES
from queueing import dispatch
from settings import DOCUMENTS, MAX_BATCH, MAX_IMAGE_BYTES, MAX_PDF_BYTES, ROOT
import storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_):
    storage.initialize()
    stop = Event()
    thread = Thread(target=dispatch, args=(stop,), daemon=True, name="kafka-dispatch")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=11)


app = FastAPI(title="多模态 PDF 问答", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/documents")
def list_documents():
    return storage.documents()


@app.post("/api/documents", status_code=202)
def upload(files: list[UploadFile] = File(...)):
    if len(files) > MAX_BATCH:
        raise HTTPException(400, f"每批最多上传 {MAX_BATCH} 份 PDF")
    accepted = []
    rejected = []
    for file in files:
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not name.lower().endswith(".pdf"):
            rejected.append({"name": name, "error": "请选择 PDF 文件"})
            continue
        payload = file.file.read(MAX_PDF_BYTES + 1)
        if len(payload) > MAX_PDF_BYTES:
            rejected.append({"name": name, "error": "单份 PDF 上限为 20 MiB"})
            continue
        if not payload.startswith(b"%PDF-"):
            rejected.append({"name": name, "error": "文件缺少 PDF 标识"})
            continue
        doc_id = uuid4().hex
        folder = DOCUMENTS / doc_id
        folder.mkdir()
        try:
            (folder / "source.pdf").write_bytes(payload)
            storage.add_document(doc_id, name)
        except Exception:
            shutil.rmtree(folder)
            logger.exception("保存上传的 PDF 失败")
            rejected.append({"name": name, "error": "保存文件失败"})
            continue
        accepted.append({"id": doc_id, "name": name, "status": "pending"})
    return {"accepted": accepted, "rejected": rejected}


@app.get("/api/documents/{doc_id}/pdf")
def original_pdf(doc_id: str):
    output = storage.document_output(doc_id)
    if not output:
        raise HTTPException(404)
    return FileResponse(output.parent / "source.pdf", media_type="application/pdf")


@app.get("/api/documents/{doc_id}/assets/{path:path}")
def document_asset(doc_id: str, path: str):
    output = storage.document_output(doc_id)
    if not output:
        raise HTTPException(404)
    asset = (output / path).resolve()
    if (not asset.is_relative_to(output / "images")
            or asset.suffix.lower() not in IMAGE_SUFFIXES or not asset.is_file()):
        raise HTTPException(404)
    return FileResponse(asset, headers={"X-Content-Type-Options": "nosniff"})


@app.post("/api/chat")
def chat(question: str = Form(...), image: UploadFile | None = File(default=None)):
    question = question.strip()
    if not 1 <= len(question) <= 3000:
        raise HTTPException(400, "请输入 1 至 3000 字的问题")
    user_image = None
    if image:
        payload = image.file.read(MAX_IMAGE_BYTES + 1)
        if len(payload) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "图片上限为 8 MiB")
        try:
            user_image = image_part(payload)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(400, "无法读取图片，请选择不超过 2400 万像素的 PNG、JPEG、GIF 或 WebP") from exc
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(503, "服务端缺少 DEEPSEEK_API_KEY")
    try:
        return answer(question, user_image, api_key)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"DeepSeek 请求失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "连接 DeepSeek 失败，请检查网络后重试") from exc
    except Exception as exc:
        logger.exception("生成回答失败")
        raise HTTPException(500, "生成回答失败，请查看 Web 服务日志") from exc
