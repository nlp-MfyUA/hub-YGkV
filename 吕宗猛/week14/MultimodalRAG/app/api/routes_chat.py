"""Multimodal chat endpoints."""
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.db.models import ChatMessage, ChatSession
from app.schemas import AskResponse, ChatMessageOut, ChatSessionOut
from app.services.files import save_chat_image
from app.services.llm_client import build_messages, call_magpie, generate_session_title, render_answer
from app.services.retrieval import retrieve

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])
settings = get_settings()


@router.get("/images/{file_name}")
def get_chat_image(file_name: str):
    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = settings.chat_upload_dir / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


@router.post("/sessions", response_model=ChatSessionOut)
def create_session(db: Session = Depends(get_db)):
    session = ChatSession(title="新会话")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(ChatSession).order_by(ChatSession.updated_at.desc()).limit(50).all()


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def list_messages(session_id: int, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )


@router.post("/ask", response_model=AskResponse)
async def ask(
    session_id: int = Form(...),
    question: str = Form(""),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    question = (question or "").strip()
    if not question and image is None:
        raise HTTPException(status_code=400, detail="问题或图片至少提供一个")

    user_image_path: Path | None = None
    if image is not None and image.filename:
        payload = await image.read()
        if len(payload) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="图片过大")
        user_image_path = save_chat_image(payload, image.filename)

    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(settings.chat_history_messages)
        .all()
    )
    history = [
        {"role": row.role, "content": row.content}
        for row in reversed(history_rows)
        if row.content
    ]

    query = question or "请描述这张图片的内容"
    chunks = [] if (user_image_path and not question) else await retrieve(query, settings.chat_top_k)
    messages = build_messages(question, chunks, history, user_image_path)
    try:
        answer = await call_magpie(messages)
    except RuntimeError as exc:
        # 单张异常图片可能让上游整次请求 400；降级为纯文本上下文重试一次。
        if "image" in str(exc).lower():
            logger.warning("Magpie 多模态请求失败，降级为纯文本重试: %s", exc)
            answer = await call_magpie(build_messages(question, chunks, history, user_image_path, include_images=False))
        else:
            raise

    image_map: dict[int, dict] = {}
    fallback: list[dict] = []
    for chunk in chunks:
        for item in chunk.images:
            image_map[item["id"]] = item
            if item["id"] not in {x["id"] for x in fallback}:
                fallback.append(item)
    rendered, used = render_answer(answer, image_map, [] if user_image_path else fallback)

    user_message = ChatMessage(
        session_id=session_id,
        role="user",
        content=question,
        image_path=f"/api/chat/images/{user_image_path.name}" if user_image_path else None,
    )
    assistant_message = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=rendered,
        image_ids=used,
    )
    db.add(user_message)
    db.add(assistant_message)
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assistant_message)

    # 会话输入完成后，用 LLM 对当前对话做摘要，作为侧栏会话标题。
    try:
        transcript_lines = [f"{item['role']}: {item['content']}" for item in history]
        transcript_lines.append(f"user: {question}")
        transcript_lines.append(f"assistant: {rendered[:600]}")
        generated_title = await generate_session_title("\n".join(transcript_lines))
        if generated_title:
            session.title = generated_title
            session.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(session)
        elif session.title == "新会话" and question:
            session.title = question[:30]
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("生成会话标题失败: %s", exc)
        if session.title == "新会话" and question:
            session.title = question[:30]
            db.commit()

    references = []
    seen = set()
    for chunk in chunks:
        key = (chunk.doc_id, chunk.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        references.append({
            "doc_id": chunk.doc_id,
            "file_name": chunk.doc_name,
            "chunk_index": chunk.chunk_index,
            "score": round(chunk.score, 4),
        })
    images = [
        {"id": image_id, "url": image_map[image_id]["url"]}
        for image_id in used
        if image_id in image_map
    ]
    return AskResponse(session_id=session_id, session_title=session.title, answer=rendered, references=references, images=images)
