"""Document upload, list, status SSE and image serving."""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.db.models import Document
from app.schemas import DocumentOut
from app.services.files import safe_file_name, save_upload
from app.services.kafka_producer import publish_parse_message
from app.services.sse import document_events

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()


def _doc_out(doc: Document) -> DocumentOut:
    return DocumentOut.model_validate(doc)


@router.post("/upload", response_model=list[DocumentOut])
async def upload_documents(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个 PDF 文件")
    created: list[Document] = []
    for upload in files:
        original = safe_file_name(upload.filename or "document.pdf")
        if not original.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"只接受 PDF 文件: {original}")
        content = await upload.read()
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb} MB: {original}")
        if not content:
            raise HTTPException(status_code=400, detail=f"空文件: {original}")
        path, size = save_upload(content, original)
        doc = Document(
            file_name=original,
            stored_path=str(path),
            file_size=size,
            status="pending",
            tier=settings.mineru_tier,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        try:
            await publish_parse_message(doc.id, doc.file_name)
        except Exception as exc:  # noqa: BLE001
            doc.status = "failed"
            doc.error_msg = f"Kafka 投递失败: {exc}"
            db.commit()
            raise HTTPException(status_code=503, detail=doc.error_msg) from exc
        created.append(doc)
    return [_doc_out(doc) for doc in created]


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    rows = db.query(Document).order_by(Document.id.desc()).all()
    return [_doc_out(doc) for doc in rows]


@router.get("/events")
async def document_status_events():
    return StreamingResponse(
        document_events(settings.sse_poll_seconds, settings.sse_heartbeat_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _doc_out(doc)


@router.post("/{doc_id}/retry", response_model=DocumentOut)
async def retry_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status not in {"failed", "pending"}:
        raise HTTPException(status_code=409, detail="只有失败或待解析文档可以重试")
    doc.status = "pending"
    doc.error_msg = None
    db.commit()
    db.refresh(doc)
    try:
        await publish_parse_message(doc.id, doc.file_name)
    except Exception as exc:  # noqa: BLE001
        doc.status = "failed"
        doc.error_msg = f"Kafka 投递失败: {exc}"
        db.commit()
        raise HTTPException(status_code=503, detail=doc.error_msg) from exc
    return _doc_out(doc)


@router.get("/{doc_id}/markdown")
def get_markdown(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc or not doc.markdown_path:
        raise HTTPException(status_code=404, detail="Markdown 尚未生成")
    path = Path(doc.markdown_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Markdown 文件不存在")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


@router.get("/{doc_id}/images/{file_name}")
def get_image(doc_id: int, file_name: str, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = settings.parsed_dir / str(doc_id) / "images" / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)
