"""作业1：用 Kafka 传递消息（生产 - 消费），配合 Redis 做幂等去重。

演示两个典型用法：
1. 任务分发：生产者发“文档解析任务”，消费者逐个处理；
2. 进度回传：消费者把处理结果写回另一个主题，生产者侧等待结果。

Kafka 负责“传”，Redis 负责“记住处理过哪些消息”，两者常见组合：
    Kafka 至少一次投递 + Redis SETNX 去重 = 业务侧幂等。

运行（先启动 compose.yml 中的 kafka，并创建主题）：
    python kafka_demo.py producer 5      # 发 5 条任务
    python kafka_demo.py consumer        # 消费并回写结果
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
import redis

BROKER = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TASK_TOPIC = "demo.task.v1"
RESULT_TOPIC = "demo.result.v1"
GROUP = "demo-worker"
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")


async def produce(count: int) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BROKER)
    await producer.start()
    try:
        for i in range(count):
            task_id = uuid.uuid4().hex[:8]
            payload = {"task_id": task_id, "kind": "parse_pdf", "name": f"报告-{i + 1}.pdf"}
            await producer.send_and_wait(TASK_TOPIC, json.dumps(payload).encode(),
                                         key=task_id.encode())
            print(f"已发送 {TASK_TOPIC}: {payload}")
    finally:
        await producer.stop()


async def consume(max_messages: int = 3) -> None:
    started = time.time()
    r = redis.from_url(REDIS_URL, decode_responses=True)
    producer = AIOKafkaProducer(bootstrap_servers=BROKER)
    await producer.start()
    consumer = AIOKafkaConsumer(TASK_TOPIC, bootstrap_servers=BROKER, group_id=GROUP,
                                auto_offset_reset="earliest", enable_auto_commit=False,
                                max_poll_records=1)
    await consumer.start()
    consumed = 0
    try:
        while consumed < max_messages:
            # 单条拉取，按需设置超时，方便演示脚本自然结束
            batches = await consumer.getmany(timeout_ms=5000, max_records=1)
            if not batches and consumed == 0 and time.time() - started > 60:
                print("60 秒内没有新消息，请先运行 producer 发送任务")
                break
            if not batches:
                if time.time() - started < 90:
                    continue   # 先等生产者上线（最长 90 秒）
                print("90 秒内没有新消息，结束演示")
                break
            for messages in batches.values():
                for msg in messages:
                    task = json.loads(msg.value)
                    dedup_key = f"demo:done:{task['task_id']}"
                    if not r.set(dedup_key, "1", nx=True, ex=3600):
                        print(f"[{task['task_id']}] 已处理过，跳过（幂等去重）")
                    else:
                        # 模拟耗时解析
                        await asyncio.sleep(0.3)
                        result = {**task, "status": "done"}
                        await producer.send_and_wait(RESULT_TOPIC,
                                                     json.dumps(result).encode(),
                                                     key=task["task_id"].encode())
                        print(f"[{task['task_id']}] 处理完成，结果已写回 {RESULT_TOPIC}")
                    await consumer.commit()
                    consumed += 1
                    if consumed >= max_messages:
                        break
    finally:
        await consumer.stop()
        await producer.stop()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "producer"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    if mode == "producer":
        asyncio.run(produce(n))
    elif mode == "consumer":
        asyncio.run(consume(n))
    else:
        raise SystemExit("usage: python kafka_demo.py producer|consumer [count]")
