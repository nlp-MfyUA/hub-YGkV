import logging
from threading import Event

from confluent_kafka import KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from settings import BROKER, DOCUMENTS, MAX_PDF_BYTES, TOPIC
import storage

logger = logging.getLogger(__name__)
MAX_RECORD_BYTES = MAX_PDF_BYTES + 1024 * 1024


def ensure_topic():
    admin = AdminClient({"bootstrap.servers": BROKER})
    topic = NewTopic(TOPIC, num_partitions=1, replication_factor=1, config={
        "max.message.bytes": str(MAX_RECORD_BYTES),
        # A stopped worker must still be able to read queued PDFs when it returns.
        "retention.ms": "-1",
    })
    try:
        admin.create_topics([topic], request_timeout=5)[TOPIC].result()
    except KafkaException as exc:
        if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise


def dispatch(stop: Event):
    producer = Producer({
        "bootstrap.servers": BROKER,
        "enable.idempotence": True,
        "message.max.bytes": MAX_RECORD_BYTES,
        "message.timeout.ms": 8000,
    })
    topic_ready = False
    while not stop.is_set():
        try:
            job = storage.pending_dispatch()
            if job is None:
                stop.wait(0.4)
                continue
            if not topic_ready:
                ensure_topic()
                topic_ready = True
            doc_id = job["id"]
            payload = (DOCUMENTS / doc_id / "source.pdf").read_bytes()
            errors = []

            def on_delivery(error, _):
                if error:
                    errors.append(error)

            producer.produce(TOPIC, key=doc_id, value=payload, on_delivery=on_delivery)
            if producer.flush(10):
                raise TimeoutError("等待 Kafka 确认超时")
            if errors:
                raise KafkaException(errors[0])
            storage.dispatched(doc_id)
        except Exception:
            topic_ready = False
            logger.exception("投递 PDF 失败，稍后重试")
            stop.wait(4)
