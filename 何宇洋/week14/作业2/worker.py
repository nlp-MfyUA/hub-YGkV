import logging
import shutil
from time import sleep

from confluent_kafka import Consumer, KafkaError, KafkaException

from parsing import parse_pdf
from queueing import ensure_topic, MAX_RECORD_BYTES
from settings import BROKER, DOCUMENTS, GROUP, MAX_PDF_BYTES, MINERU_TIMEOUT, TOPIC
import storage

logger = logging.getLogger(__name__)


def process(message):
    doc_id = (message.key() or b"").decode("ascii", errors="replace")
    attempt = storage.claim(doc_id)
    if not attempt:
        return
    output = DOCUMENTS / doc_id / attempt
    logger.info("开始解析 %s", doc_id)
    try:
        payload = message.value() or b""
        if not payload.startswith(b"%PDF-") or len(payload) > MAX_PDF_BYTES:
            raise ValueError("Kafka 中的 PDF 数据无效")
        chunks = parse_pdf(payload, output)
    except Exception as exc:
        logger.exception("解析失败 %s", doc_id)
        (output / "input.pdf").unlink(missing_ok=True)
        (output / "mineru.zip").unlink(missing_ok=True)
        storage.finish(doc_id, attempt, error=f"解析或建立索引失败（{type(exc).__name__}）。请查看 worker 日志。")
    else:
        if storage.finish(doc_id, attempt, chunks):
            logger.info("解析完成 %s，%s 个片段", doc_id, len(chunks))
        else:
            shutil.rmtree(output)


def consume():
    ensure_topic()
    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "max.poll.interval.ms": (MINERU_TIMEOUT + 600) * 1000,
        "max.partition.fetch.bytes": MAX_RECORD_BYTES,
        "fetch.max.bytes": MAX_RECORD_BYTES * 2,
    })
    try:
        consumer.subscribe([TOPIC])
        logger.info("监听 Kafka 主题 %s", TOPIC)
        while True:
            message = consumer.poll(1)
            if message is None:
                continue
            if message.error():
                if message.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(message.error())
            process(message)
            for partition in consumer.commit(message=message, asynchronous=False):
                if partition.error:
                    raise KafkaException(partition.error)
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    storage.initialize()
    try:
        while True:
            try:
                consume()
            except KafkaException:
                logger.exception("Kafka 连接或提交失败，5 秒后重新连接")
                sleep(5)
    except KeyboardInterrupt:
        pass
