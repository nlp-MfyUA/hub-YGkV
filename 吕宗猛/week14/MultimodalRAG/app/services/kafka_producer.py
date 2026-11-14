"""Kafka producer singleton."""
import json
import logging

from aiokafka import AIOKafkaProducer

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
_producer: AIOKafkaProducer | None = None


async def start_producer() -> None:
    global _producer
    if not settings.kafka_enabled or _producer is not None:
        return
    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        client_id=settings.kafka_client_id,
    )
    await _producer.start()
    logger.info("Kafka producer started: %s", settings.kafka_bootstrap_servers)


async def stop_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def publish_parse_message(doc_id: int, file_name: str) -> None:
    if not settings.kafka_enabled:
        logger.warning("Kafka disabled; document %s will stay pending", doc_id)
        return
    if _producer is None:
        raise RuntimeError("Kafka producer 未启动")
    payload = json.dumps({"doc_id": doc_id, "file_name": file_name}, ensure_ascii=False).encode()
    await _producer.send_and_wait(settings.kafka_topic, key=str(doc_id).encode(), value=payload)
