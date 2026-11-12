#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kafka 封装：topic 管理、生产者、消费者、堆积量查询。

三个 topic 的分工：
  rag.doc.parse       任务流。key=doc_id → 同一篇文档永远进同一分区，
                      多 worker 时不会有两个实例同时解析同一份文件。
  rag.doc.status      状态流。每次 PENDING/PARSING/DONE/FAILED 变更发一条，
                      用于审计、监控，以及后续接「通知」「重跑」等下游。
  rag.doc.parse.dlq   死信。重试用尽仍失败的任务落到这里，人工介入，不再占用主流量。
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

from config import (KAFKA_BOOTSTRAP, PARSE_PARTITIONS, TOPIC_DLQ, TOPIC_PARSE,
                    TOPIC_STATUS)

log = logging.getLogger("bus")

# kafka-python 3.x 里 NoBrokersAvailable 的位置变过，做兼容
try:
    from kafka.errors import NoBrokersAvailable
except ImportError:                                     # pragma: no cover
    NoBrokersAvailable = ConnectionError


# ---------------------------------------------------------------- Topic
def ensure_topics(bootstrap: str = KAFKA_BOOTSTRAP) -> List[str]:
    """幂等建 topic。parse 用 3 分区，其余 1 分区。"""
    admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=15000)
    out = []
    spec = [(TOPIC_PARSE, PARSE_PARTITIONS), (TOPIC_STATUS, 1), (TOPIC_DLQ, 1)]
    try:
        for name, parts in spec:
            try:
                admin.create_topics([NewTopic(name=name, num_partitions=parts,
                                              replication_factor=1)], validate_only=False)
                out.append(f"created {name}({parts}p)")
            except TopicAlreadyExistsError:
                out.append(f"exists {name}")
    finally:
        admin.close()
    return out


def list_topics(bootstrap: str = KAFKA_BOOTSTRAP) -> List[str]:
    admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=15000)
    try:
        return sorted(t for t in admin.list_topics() if not t.startswith("__"))
    finally:
        admin.close()


# ---------------------------------------------------------------- 生产者
_producer: Optional[KafkaProducer] = None


def get_producer(bootstrap: str = KAFKA_BOOTSTRAP) -> KafkaProducer:
    """进程内单例。KafkaProducer 本身线程安全，可以给 FastAPI 的多个请求共用。"""
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=bootstrap,
            acks="all",                 # 等所有 ISR 落盘，任务不能丢
            retries=5,
            linger_ms=5,
            batch_size=16384,
            max_in_flight_requests_per_connection=5,
        )
    return _producer


def _send(topic: str, key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    p = get_producer()
    md = p.send(topic, key=key.encode("utf-8"),
                value=json.dumps(payload, ensure_ascii=False).encode("utf-8")).get(timeout=15)
    p.flush()
    return {"topic": md.topic, "partition": md.partition, "offset": md.offset}


def publish_parse(doc_id: str, filename: str, file_path: str, attempt: int = 1) -> Dict[str, Any]:
    """投递解析任务。key=doc_id 保证单文档有序、不并发。"""
    return _send(TOPIC_PARSE, doc_id, {
        "event": "parse.request",
        "doc_id": doc_id,
        "filename": filename,
        "file_path": file_path,
        "attempt": attempt,
        "ts": time.time(),
    })


def publish_status(doc_id: str, status: str, **extra) -> Dict[str, Any]:
    payload = {"event": "doc.status", "doc_id": doc_id, "status": status,
               "ts": time.time(), "ts_text": time.strftime("%H:%M:%S")}
    payload.update(extra)
    return _send(TOPIC_STATUS, doc_id, payload)


def publish_dlq(doc_id: str, reason: str, attempts: int) -> Dict[str, Any]:
    return _send(TOPIC_DLQ, doc_id, {"event": "parse.dead", "doc_id": doc_id,
                                     "reason": reason, "attempts": attempts, "ts": time.time()})


def publish_retry(doc_id: str, filename: str, file_path: str, attempt: int) -> Dict[str, Any]:
    """重试就是「再投一次同样的任务 + attempt+1」，靠 Kafka 自己排队，不用额外调度器。"""
    return publish_parse(doc_id, filename, file_path, attempt=attempt)


# ---------------------------------------------------------------- 消费者
def build_consumer(group_id: str, topics: List[str],
                   bootstrap: str = KAFKA_BOOTSTRAP) -> KafkaConsumer:
    """手动提交位点的消费者：处理成功才 commit，保证 at-least-once。"""
    return KafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=-1,        # 关掉内置超时退出，循环自己控
        max_poll_records=10,
        max_poll_interval_ms=1800000,  # 单篇解析可能很久，别让 rebalance 把任务抢走
        session_timeout_ms=30000,
        heartbeat_interval_ms=10000,
    )


# ---------------------------------------------------------------- 观测
def lag_snapshot(group_id: str, topic: str = TOPIC_PARSE,
                 bootstrap: str = KAFKA_BOOTSTRAP) -> List[Dict[str, Any]]:
    """每个分区的 LEO / 已提交位点 / 堆积量。前端右上角的「管道状态」用它。"""
    c = KafkaConsumer(bootstrap_servers=bootstrap, group_id=group_id,
                      enable_auto_commit=False, consumer_timeout_ms=-1)
    try:
        parts = sorted(c.partitions_for_topic(topic) or [])
        tps = [TopicPartition(topic, p) for p in parts]
        if not tps:
            return []
        c.assign(tps)
        end = c.end_offsets(tps)
        out = []
        for tp in tps:
            committed = c.committed(tp) or 0
            out.append({"partition": tp.partition, "leo": end[tp],
                        "committed": committed, "lag": max(0, end[tp] - committed)})
        return out
    finally:
        c.close()


def health(bootstrap: str = KAFKA_BOOTSTRAP) -> Dict[str, Any]:
    try:
        topics = list_topics(bootstrap)
        return {"ok": True, "topics": topics}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
