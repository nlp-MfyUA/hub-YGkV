"""用 Kafka 发送和消费消息。依赖：python -m pip install confluent-kafka。"""

import argparse
import json
import os
import sys
from time import monotonic

from confluent_kafka import Consumer, KafkaException, Producer


def send(broker: str, topic: str, text: str) -> None:
    producer = Producer({"bootstrap.servers": broker, "message.timeout.ms": 10000})
    delivery_error = None

    def on_delivery(error, message):
        nonlocal delivery_error
        delivery_error = error
        if error is None:
            print(f"已发送到 {message.topic()}[{message.partition()}] offset={message.offset()}")

    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    producer.produce(topic, value=payload, on_delivery=on_delivery)
    if producer.flush(12):
        raise TimeoutError("发送确认超时")
    if delivery_error is not None:
        raise KafkaException(delivery_error)


def receive(broker: str, topic: str, group: str, count: int, timeout: int) -> None:
    consumer = Consumer({
        "bootstrap.servers": broker,
        "group.id": group,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    try:
        consumer.subscribe([topic])
        deadline = monotonic() + timeout
        received = 0
        while received < count:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError(f"等待消息超时，已接收 {received}/{count} 条")
            message = consumer.poll(min(1.0, remaining))
            if message is None:
                continue
            if message.error() is not None:
                raise KafkaException(message.error())

            payload = message.value()
            body = "null" if payload is None else payload.decode("utf-8")
            print(f"{message.topic()}[{message.partition()}] offset={message.offset()} {body}", flush=True)

            # 处理成功后提交，下一次使用同一消费组时从已提交的位置继续。
            for partition in consumer.commit(message=message, asynchronous=False):
                if partition.error is not None:
                    raise KafkaException(partition.error)
            received += 1
    finally:
        consumer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="向 Kafka 发送和消费 UTF-8 消息")
    parser.add_argument("--broker", default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"))
    parser.add_argument("--topic", default="wk14-messages", help="Kafka 主题，默认 wk14-messages")
    commands = parser.add_subparsers(dest="command", required=True)

    producer = commands.add_parser("send", help="发送一条 JSON 消息")
    producer.add_argument("text", help="消息内容")

    consumer = commands.add_parser("receive", help="消费消息并提交 offset")
    consumer.add_argument("--group", default="wk14-demo", help="消费组，默认 wk14-demo")
    consumer.add_argument("--count", type=int, default=1, help="接收条数，默认 1")
    consumer.add_argument("--timeout", type=int, default=20, help="等待消息的总秒数，默认 20")

    args = parser.parse_args()
    if args.command == "receive" and (args.count < 1 or args.timeout < 1):
        consumer.error("--count 和 --timeout 必须大于 0")

    try:
        if args.command == "send":
            send(args.broker, args.topic, args.text)
        else:
            receive(args.broker, args.topic, args.group, args.count, args.timeout)
    except (KafkaException, TimeoutError, UnicodeError) as exc:
        print(f"Kafka 操作失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
