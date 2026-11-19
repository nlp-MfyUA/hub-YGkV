"""SSE document status stream backed by MySQL polling."""
import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import AsyncIterator

from app.core.db import SessionLocal
from app.db.models import Document

logger = logging.getLogger(__name__)
settings = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _snapshot() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(Document).order_by(Document.id.desc()).all()
        return [
            {
                "id": r.id,
                "file_name": r.file_name,
                "file_size": r.file_size,
                "status": r.status,
                "tier": r.tier,
                "page_count": r.page_count,
                "chunk_count": r.chunk_count,
                "image_count": r.image_count,
                "error_msg": r.error_msg,
                "created_at": _iso(r.created_at),
                "updated_at": _iso(r.updated_at),
                "parsed_at": _iso(r.parsed_at),
            }
            for r in rows
        ]
    finally:
        db.close()


async def document_events(poll_seconds: float = 1.0, heartbeat_seconds: float = 15.0) -> AsyncIterator[str]:
    last_hash = ""
    last_emit = 0.0
    yield "retry: 3000\n\n"
    while True:
        docs = await asyncio.to_thread(_snapshot)
        payload = json.dumps(docs, ensure_ascii=False, default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        now = asyncio.get_event_loop().time()
        if digest != last_hash:
            yield f"event: documents\ndata: {payload}\n\n"
            last_hash = digest
            last_emit = now
        elif now - last_emit >= heartbeat_seconds:
            yield ": ping\n\n"
            last_emit = now
        await asyncio.sleep(max(0.2, poll_seconds))
