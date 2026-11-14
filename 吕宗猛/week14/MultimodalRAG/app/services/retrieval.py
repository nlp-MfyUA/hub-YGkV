"""Vector retrieval over MySQL-stored chunk embeddings."""
import asyncio
import logging
from dataclasses import dataclass, field

from app.core.db import SessionLocal
from app.db.models import Chunk, Document, Image
from app.services.embeddings import cosine, embed_texts, unpack_vector
from app.services.files import image_url

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    doc_id: int
    doc_name: str
    chunk_index: int
    content: str
    score: float
    images: list[dict] = field(default_factory=list)


def _load_rows() -> list[tuple[Chunk, Document]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(Chunk, Document)
            .join(Document, Chunk.doc_id == Document.id)
            .filter(Document.status == "completed")
            .all()
        )
        return [(c, d) for c, d in rows]
    finally:
        db.close()


def _load_images(image_ids: list[int]) -> dict[int, Image]:
    if not image_ids:
        return {}
    db = SessionLocal()
    try:
        rows = db.query(Image).filter(Image.id.in_(image_ids)).all()
        return {r.id: r for r in rows}
    finally:
        db.close()


async def retrieve(query: str, top_k: int = 6) -> list[RetrievedChunk]:
    if not query.strip():
        return []
    query_vec = (await embed_texts([query]))[0]
    rows = await asyncio.to_thread(_load_rows)
    scored: list[tuple[float, Chunk, Document]] = []
    for chunk, doc in rows:
        vec = unpack_vector(chunk.embedding)
        scored.append((cosine(query_vec, vec), chunk, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[: max(1, top_k)]

    all_ids: list[int] = []
    for _, chunk, _ in top:
        for image_id in (chunk.image_ids or []):
            if image_id not in all_ids:
                all_ids.append(image_id)
    image_map = await asyncio.to_thread(_load_images, all_ids)

    result: list[RetrievedChunk] = []
    for score, chunk, doc in top:
        images = []
        for image_id in (chunk.image_ids or []):
            image = image_map.get(image_id)
            if image:
                images.append({
                    "id": image.id,
                    "file_name": image.file_name,
                    "url": image_url(doc.id, image.file_name),
                    "path": image.file_path,
                    "mime_type": image.mime_type,
                })
        result.append(RetrievedChunk(
            chunk_id=chunk.id,
            doc_id=doc.id,
            doc_name=doc.file_name,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            score=score,
            images=images,
        ))
    return result
