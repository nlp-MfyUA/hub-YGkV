#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kafka 实践 2/2：用 Kafka 传递行情消息
=========================================

场景：行情网关把 tick 推给下游（选股、风控、落库），要求：
  1) 同一只股票的消息严格有序（否则价格会"倒着走"）
  2) 下游可以多实例并行消费、横向扩容
  3) 消费位点可控（手动提交，处理成功再提交，避免丢消息）

核心概念对应到代码：
  topic + partition  -> 并行单元；同 key 的消息一定进同一分区 -> 分区内有序
  key                -> 用股票代码做 key，hash 到固定分区，天然保证单票有序
  consumer group     -> 同组内多实例分摊分区（一条消息只被组内一个实例消费）
  offset 提交        -> enable_auto_commit=False + 处理完再 commit，实现 at-least-once

用法：
  python3 kafka_messaging.py demo                     # 一键演示
  python3 kafka_messaging.py produce --count 10       # 只生产
  python3 kafka_messaging.py consume --timeout 10     # 只消费
  python3 kafka_messaging.py lag                      # 查看消费进度(堆积量)
  python3 kafka_messaging.py reset                    # 删除重建 topic
"""

import argparse
import json
import random
import sys
import time
from typing import Dict, List, Optional

from kafka import KafkaProducer, KafkaConsumer, TopicPartition
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

# kafka-python 3.x 把 NoBrokersAvailable 挪走了，做兼容
try:
    from kafka.errors import NoBrokersAvailable
except ImportError:                                     # pragma: no cover
    NoBrokersAvailable = ConnectionError

# ------------------------------------------------------------------ 配置
BOOTSTRAP = "127.0.0.1:9092"
TOPIC = "hl-test-ticks"
GROUP_ID = "hl-test-group"
NUM_PARTITIONS = 3
STOCKS = ["600519", "000858", "601318", "300750"]

SEP = "-" * 78


# ------------------------------------------------------------------ Topic 管理
def ensure_topic(bootstrap: str = BOOTSTRAP, topic: str = TOPIC,
                 partitions: int = NUM_PARTITIONS) -> str:
    """幂等建 topic：已存在就跳过。"""
    admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=15000)
    try:
        admin.create_topics([NewTopic(name=topic, num_partitions=partitions,
                                      replication_factor=1)], validate_only=False)
        msg = f"已创建 topic {topic}（{partitions} 分区）"
    except TopicAlreadyExistsError:
        msg = f"topic {topic} 已存在，跳过创建"
    finally:
        admin.close()
    return msg


def reset_topic(bootstrap: str = BOOTSTRAP, topic: str = TOPIC,
                partitions: int = NUM_PARTITIONS) -> str:
    """删除后重建 —— 演示时想要"干净的分区/位点"用它。"""
    admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=15000)
    try:
        admin.delete_topics([topic], timeout_ms=15000)
        time.sleep(2)
    except Exception:
        pass
    try:
        admin.create_topics([NewTopic(name=topic, num_partitions=partitions,
                                      replication_factor=1)])
        out = f"已重建 topic {topic}（{partitions} 分区）"
    except TopicAlreadyExistsError:
        out = f"topic {topic} 重建失败：仍存在"
    finally:
        admin.close()
    return out


# ------------------------------------------------------------------ 生产者
def build_producer(bootstrap: str = BOOTSTRAP) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=bootstrap,
        # 不传 serializer 对象：kafka-python 3.x 对旧式 lambda 序列化器已弃用，
        # 统一在 send() 时手动编码成 bytes，跨版本最稳。
        acks="all",                 # 所有 ISR 落盘才返回，最强持久性
        retries=3,
        linger_ms=5,                # 攒 5ms 再发，提高批量吞吐
        batch_size=16384,
        max_in_flight_requests_per_connection=5,
    )


def gen_tick(code: str) -> Dict:
    """造一条行情 tick。"""
    price = round(random.uniform(10, 1800), 2)
    return {
        "code": code,
        "price": price,
        "volume": random.randint(100, 50000),
        "ts": int(time.time() * 1000),
        "seq": random.randint(1, 999999),
    }


def produce(producer: KafkaProducer, count: int = 12, topic: str = TOPIC) -> List[Dict]:
    """发消息。注意 key=股票代码 —— 同票必进同分区，保证单票有序。"""
    sent = []
    for i in range(count):
        code = STOCKS[i % len(STOCKS)]
        tick = gen_tick(code)
        fut = producer.send(
            topic,
            key=code.encode("utf-8"),                                # key 决定分区
            value=json.dumps(tick, ensure_ascii=False).encode("utf-8"),
        )
        md = fut.get(timeout=10)          # 同步等 broker 确认，拿到分区和 offset
        sent.append({"code": code, "partition": md.partition, "offset": md.offset,
                     "price": tick["price"]})
    producer.flush()
    return sent


# ------------------------------------------------------------------ 消费者
def build_consumer(bootstrap: str = BOOTSTRAP, group_id: str = GROUP_ID,
                   topic: str = TOPIC) -> KafkaConsumer:
    return KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        auto_offset_reset="earliest",     # 新组从最早开始读
        enable_auto_commit=False,         # 关键：手动提交，处理成功才推进位点
        consumer_timeout_ms=-1,           # 不靠超时退循环，自己控制
        max_poll_records=50,
    )


def consume_loop(consumer: KafkaConsumer, timeout: float = 8.0,
                 verbose: bool = True) -> List[Dict]:
    """手动 poll + 手动 commit 的消费循环（at-least-once 的典型写法）。"""
    got: List[Dict] = []
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            records = consumer.poll(timeout_ms=500)
            if not records:
                continue
            for tp, batch in records.items():
                for rec in batch:
                    key = rec.key.decode("utf-8") if rec.key else None
                    val = json.loads(rec.value.decode("utf-8"))
                    item = {
                        "partition": rec.partition,
                        "offset": rec.offset,
                        "key": key,
                        "value": val,
                    }
                    got.append(item)
                    if verbose:
                        print(f"    [消费] P{rec.partition}@{rec.offset:<5} "
                              f"{key:<7} price={val['price']:<9} vol={val['volume']}")
            # 业务处理完后统一提交本批位点；提交的是 offset+1
            consumer.commit()
    finally:
        consumer.close()
    return got


def lag_report(bootstrap: str = BOOTSTRAP, group_id: str = GROUP_ID,
               topic: str = TOPIC) -> List[Dict]:
    """查看每个分区的堆积量 = LEO(日志末端位点) - 已提交位点。"""
    c = KafkaConsumer(bootstrap_servers=bootstrap, group_id=group_id,
                      enable_auto_commit=False)
    parts = [TopicPartition(topic, p) for p in
             sorted(c.partitions_for_topic(topic) or [])]
    c.assign(parts)
    end = c.end_offsets(parts)
    committed = {tp: (c.committed(tp) or 0) for tp in parts}
    out = []
    for tp in parts:
        out.append({"partition": tp.partition,
                    "leo": end[tp],
                    "committed": committed[tp],
                    "lag": end[tp] - committed[tp]})
    c.close()
    return out


# ------------------------------------------------------------------ 演示
def cmd_demo(args):
    print("=" * 78)
    print("Kafka 消息传递演示")
    print("=" * 78)

    print(f"\n[0] 准备 topic")
    print("    " + reset_topic(partitions=NUM_PARTITIONS))

    producer = build_producer()

    print(f"\n[1] 生产 12 条 tick（key=股票代码，value=JSON）")
    sent = produce(producer, count=12)
    for s in sent:
        print(f"    [生产] {s['code']:<7} -> 分区 P{s['partition']} @offset {s['offset']:<4} "
              f"price={s['price']}")

    # 分组统计，证明"同 key 同分区"
    by_code: Dict[str, set] = {}
    for s in sent:
        by_code.setdefault(s["code"], set()).add(s["partition"])
    print("\n[2] 验证 key -> partition 的映射（这就是单票有序的原因）")
    for code, ps in by_code.items():
        print(f"    {code:<7} 落在分区 {sorted(ps)}  "
              f"-> {'稳定，单票有序 ✔' if len(ps) == 1 else '跨分区 ✘'}")

    print(f"\n[3] 消费者拉取（group={GROUP_ID}，手动提交 offset）")
    consumer = build_consumer()
    got = consume_loop(consumer, timeout=6)
    print(f"    共消费 {len(got)} 条")

    print("\n[4] 按分区统计消费分布")
    dist: Dict[int, int] = {}
    for g in got:
        dist[g["partition"]] = dist.get(g["partition"], 0) + 1
    for p in sorted(dist):
        print(f"    分区 P{p}: {dist[p]} 条")
    print(f"    说明：{len(by_code)} 只股票分布在 {len(dist)} 个分区上，"
          f"下游可用 {len(dist)} 个实例并行消费")

    print("\n[5] 消费进度 / 堆积量（LEO - committed）")
    for r in lag_report():
        print(f"    分区 P{r['partition']}: LEO={r['leo']:<4} "
              f"committed={r['committed']:<4} lag={r['lag']}")

    print("\n[6] 再消费一次 —— 位点已提交，不会重复消费老消息")
    again = consume_loop(build_consumer(), timeout=3, verbose=False)
    print(f"    本次拉到 {len(again)} 条（期望 0，说明 offset 提交生效）")

    print("\n[7] 从头回放（模拟新消费组 / 补数据场景，earliest）")
    replay = build_consumer(group_id="hl-replay-group")
    n = len(consume_loop(replay, timeout=4, verbose=False))
    print(f"    新 group 从 earliest 起读，拉到 {n} 条历史消息")

    producer.close()
    print("\n演示结束。")


def main():
    p = argparse.ArgumentParser(description="Kafka 消息传递实践")
    p.add_argument("--bootstrap", default=BOOTSTRAP)
    p.add_argument("--topic", default=TOPIC)
    p.add_argument("--group", default=GROUP_ID)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="一键演示")
    d.add_argument("--count", type=int, default=12)

    pr = sub.add_parser("produce", help="生产消息")
    pr.add_argument("--count", type=int, default=10)

    co = sub.add_parser("consume", help="消费消息")
    co.add_argument("--timeout", type=float, default=10)
    co.add_argument("--group", default=None, help="消费组，默认 hl-test-group")

    sub.add_parser("lag", help="查看消费进度")
    sub.add_parser("reset", help="删除并重建 topic")

    args = p.parse_args()

    # 本机有 HTTP 代理时，Kafka/Redis 走裸 socket 不受影响，
    # 但保险起见这里不读代理配置（kafka-python 本身不认 http_proxy）。
    try:
        if args.cmd == "demo":
            cmd_demo(args)
        elif args.cmd == "produce":
            ensure_topic(args.bootstrap, args.topic)
            pr = build_producer(args.bootstrap)
            for s in produce(pr, args.count, args.topic):
                print(f"{s['code']:<7} -> P{s['partition']}@{s['offset']}")
            pr.close()
        elif args.cmd == "consume":
            group = args.group or GROUP_ID
            print(f"消费组 {group}，最多等待 {args.timeout}s …")
            got = consume_loop(build_consumer(args.bootstrap, group, args.topic),
                               args.timeout)
            print(f"共消费 {len(got)} 条")
        elif args.cmd == "lag":
            for r in lag_report(args.bootstrap, args.group, args.topic):
                print(f"P{r['partition']}  LEO={r['leo']:<5} committed={r['committed']:<5} lag={r['lag']}")
        elif args.cmd == "reset":
            print(reset_topic(args.bootstrap, args.topic))
    except NoBrokersAvailable:
        print(f"连不上 Kafka broker {args.bootstrap}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
