"""Kafka consumer worker for PDF parsing and indexing."""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from aiokafka import AIOKafkaConsumer

from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.core.logging import setup_logging
from app.db.models import Chunk, Document, Image
from app.services.chunker import chunk_markdown
from app.services.embeddings import embed_texts, pack_vector
from app.services.files import save_mineru_zip
from app.services.mineru_client import parse_pdf

logger = logging.getLogger(__name__)
settings = get_settings()


async def process_document(doc_id: int) -> None:
    db = SessionLocal()
    doc = db.get(Document, doc_id)
    if not doc:
        db.close()
        logger.warning("document %s not found", doc_id)
        return
    if doc.status == "completed":
        db.close()
        logger.info("document %s already completed", doc_id)
        return
    doc.status = "parsing"
    doc.error_msg = None
    doc.updated_at = datetime.utcnow()
    db.commit()
    try:
        zip_bytes = await parse_pdf(Path(doc.stored_path), doc.tier)
        markdown, images = await asyncio.to_thread(save_mineru_zip, doc_id, zip_bytes)
        image_rows: list[Image] = []
        for item in images:
            row = Image(
                doc_id=doc_id,
                file_name=item["file_name"],
                file_path=item["file_path"],
                mime_type=item["mime_type"],
            )
            db.add(row)
            db.flush()
            image_rows.append(row)
        image_id_by_name = {row.file_name: row.id for row in image_rows}
        chunks = chunk_markdown(markdown, image_id_by_name)
        if not chunks:
            raise RuntimeError("MinerU 输出中没有可索引的文本块")
        vectors = await embed_texts([item["content"] for item in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("embedding 数量与 chunk 数量不一致")
        for item, vector in zip(chunks, vectors):
            db.add(Chunk(
                doc_id=doc_id,
                chunk_index=item["chunk_index"],
                content=item["content"],
                token_count=item["token_count"],
                image_ids=item["image_ids"],
                embedding=pack_vector(vector),
            ))
        doc.status = "completed"
        doc.chunk_count = len(chunks)
        doc.image_count = len(images)
        doc.markdown_path = str(settings.parsed_dir / str(doc_id) / "document.md")
        doc.parsed_at = datetime.utcnow()
        doc.error_msg = None
        doc.updated_at = datetime.utcnow()
        db.commit()
        logger.info("document %s parsed: %s chunks, %s images", doc_id, len(chunks), len(images))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("document %s parse failed", doc_id)
        fresh = db.get(Document, doc_id)
        if fresh:
            fresh.status = "failed"
            fresh.error_msg = str(exc)[:2000]
            fresh.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


async def main() -> None:
    setup_logging()
    init_db()
    settings.ensure_dirs()
    consumer = AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_group,
        client_id=settings.kafka_client_id + "-worker",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    while True:
        try:
            await consumer.start()
            break
        except Exception as exc:  # noqa: BLE001
            logger.error("Kafka consumer 启动失败: %s; 5 秒后重试", exc)
            await asyncio.sleep(5)
    logger.info("worker started, topic=%s", settings.kafka_topic)
    try:
        async for message in consumer:
            try:
                payload = json.loads(message.value.decode("utf-8"))
                await process_document(int(payload["doc_id"]))
            except Exception:  # noqa: BLE001
                logger.exception("bad kafka message: %s", message.value[:500])
            finally:
                await consumer.commit()
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
