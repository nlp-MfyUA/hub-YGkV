#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 worker：消费 Kafka 任务 → MinerU 解析 → 切块 → 入库 → 建索引 → 发状态。

可靠性的三个约定：
  1. **手动提交位点**：处理完（含重试/死信决策）才 commit。进程被 kill 时位点不前进，
     Kafka 会重投；重投后靠 DB 里的状态做幂等（DONE 直接跳过）。
  2. **业务失败不用「不提交」来重试**：那样会卡住整个分区。这里的做法是
     显式再投一条 attempt+1 的消息，然后正常提交 —— 死信和重试都走 Kafka 自己排队。
  3. **状态先落库再发事件**：前端轮询以 MySQL 为准，Kafka 的 status topic 是旁路通知，
     丢一条事件不影响用户看到的状态。

用法：
  python3 parse_worker.py run                # 常驻消费
  python3 parse_worker.py once path/to.pdf   # 绕过 Kafka 直接解析，调试解析链路
  python3 parse_worker.py lag                # 看各分区堆积
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict

import bus
import chunker
import config
import db
import indexer
import mineru_runner

log = logging.getLogger("worker")
_running = True


def _setup_log(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # kafka-python 每个连接都打一屏 INFO，压掉；httpx 的请求日志同理
    for noisy in ("kafka", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _on_term(signum, _frame):                            # noqa: ARG001
    global _running
    _running = False
    log.warning("收到信号 %s，处理完当前任务后退出（位点会正常提交）", signum)


# ---------------------------------------------------------------- 核心流程
def process_document(doc_id: str, file_path: str, filename: str,
                     attempt: int = 1) -> Dict[str, Any]:
    """解析 + 入库 + 建索引。调用方负责状态机的重试/死信判断。"""
    doc_id_short = doc_id
    t0 = time.time()
    db.mark_parsing(doc_id, str(config.WORK_DIR / doc_id_short))
    bus.publish_status(doc_id, db.STATUS_PARSING, filename=filename, attempt=attempt)

    result = mineru_runner.parse_pdf(file_path, doc_id)          # 可能抛异常
    chunks = chunker.build_chunks(doc_id, result["blocks"])
    db.replace_chunks(doc_id, chunks)
    indexer.index_chunks(doc_id, filename, chunks)
    db.mark_done(doc_id, result["pages"], len(chunks), result["n_images"],
                 round(time.time() - t0, 2), result["engine"])

    n_img = sum(1 for c in chunks if c["kind"] == "image")
    n_tab = sum(1 for c in chunks if c["kind"] == "table")
    bus.publish_status(doc_id, db.STATUS_DONE, filename=filename,
                       pages=result["pages"], n_chunks=len(chunks),
                       n_images=n_img, n_tables=n_tab,
                       seconds=round(time.time() - t0, 2))
    return {"doc_id": doc_id, "chunks": len(chunks), "images": n_img,
            "tables": n_tab, "pages": result["pages"],
            "seconds": round(time.time() - t0, 2)}


def handle_message(raw: bytes) -> None:
    """处理一条 Kafka 消息。异常在这里被转成「重试」或「死信」，不往外抛。"""
    try:
        msg = json.loads(raw.decode("utf-8"))
    except Exception as e:                                   # noqa: BLE001
        log.error("消息无法解析，直接丢进死信：%s (%s)", raw[:200], e)
        bus.publish_dlq("unknown", f"bad json: {e}", 0)
        return

    doc_id = msg.get("doc_id")
    attempt = int(msg.get("attempt") or 1)
    log.info("▶ 收到任务 doc=%s attempt=%s file=%s", doc_id, attempt, msg.get("filename"))

    doc = db.get_document(doc_id) if doc_id else None
    if not doc:
        log.warning("文档 %s 不在库里（可能已被删除），跳过", doc_id)
        return
    if doc["status"] == db.STATUS_DONE:
        log.info("文档 %s 已是 DONE，跳过（幂等）", doc_id)
        return

    try:
        stats = process_document(doc_id, doc["file_path"], doc["filename"], attempt)
        log.info("✅ 完成 doc=%s 页=%s 块=%s 图=%s 表=%s 耗时=%ss",
                 doc_id, stats["pages"], stats["chunks"], stats["images"],
                 stats["tables"], stats["seconds"])
    except Exception as e:                                   # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.error("❌ 解析失败 doc=%s attempt=%s/%s: %s",
                  doc_id, attempt, config.MAX_ATTEMPTS, err[:500])
        if attempt < config.MAX_ATTEMPTS:
            # 显式重投：状态退回待解析，前端能看到「重试中」
            db.reset_to_pending(doc_id, err)
            bus.publish_status(doc_id, db.STATUS_PENDING, filename=doc["filename"],
                               retry=True, attempt=attempt + 1, error=err[:300])
            bus.publish_retry(doc_id, doc["filename"], doc["file_path"], attempt + 1)
            log.warning("已重新投递 doc=%s（第 %s 次尝试）", doc_id, attempt + 1)
        else:
            db.mark_failed(doc_id, err)
            bus.publish_status(doc_id, db.STATUS_FAILED, filename=doc["filename"],
                               error=err[:300], attempt=attempt)
            bus.publish_dlq(doc_id, err[:500], attempt)
            log.error("重试用尽，已写入死信 topic %s", config.TOPIC_DLQ)


def run_forever() -> int:
    db.init_database()
    indexer.ensure_index()
    log.info("topic: %s", ", ".join(bus.ensure_topics()))

    consumer = bus.build_consumer(config.CONSUMER_GROUP, [config.TOPIC_PARSE])
    log.info("worker 已启动 group=%s topic=%s bootstrap=%s",
             config.CONSUMER_GROUP, config.TOPIC_PARSE, config.KAFKA_BOOTSTRAP)
    log.info("mineru=%s remote=%s tier=%s", config.MINERU_BIN,
             config.MINERU_REMOTE_URL or "(local)", config.MINERU_TIER)
    try:
        while _running:
            records = consumer.poll(timeout_ms=config.POLL_TIMEOUT_MS)
            if not records:
                continue
            for tp, batch in records.items():
                for rec in batch:
                    if not _running:
                        log.warning("准备退出，剩余 %s 条消息留给下一次启动", 1)
                        return 0
                    log.debug("offset=%s partition=%s", rec.offset, tp.partition)
                    handle_message(rec.value)
            # 本批处理完统一提交：提交的是「下一条要读的位置」
            consumer.commit()
    finally:
        consumer.close()
        log.info("consumer 已关闭")
    return 0


# ---------------------------------------------------------------- 调试入口
def run_once(pdf_path: str) -> int:
    db.init_database()
    indexer.ensure_index()
    bus.ensure_topics()
    path = os.path.abspath(pdf_path)
    if not os.path.exists(path):
        log.error("文件不存在：%s", path)
        return 1
    sha = db.sha256_of(path)
    existing = db.find_by_sha(sha)
    if existing:
        log.info("同名内容已存在，复用 doc_id=%s", existing["id"])
        doc_id = existing["id"]
        db.reset_to_pending(doc_id, "")
    else:
        doc_id = db.new_doc_id(sha)
        target = config.UPLOAD_DIR / f"{doc_id}.pdf"
        with open(path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        db.create_document(doc_id, os.path.basename(path),
                           os.path.getsize(path), sha, str(target))
    try:
        stats = process_document(doc_id, str(config.UPLOAD_DIR / f"{doc_id}.pdf"),
                                 os.path.basename(path), 1)
    except Exception as e:                                   # noqa: BLE001
        db.mark_failed(doc_id, f"{type(e).__name__}: {e}")
        log.error("解析失败：%s", e)
        return 1
    log.info("解析结果：%s", json.dumps(stats, ensure_ascii=False))
    return 0


def show_lag() -> int:
    rows = bus.lag_snapshot(config.CONSUMER_GROUP)
    if not rows:
        print("topic 尚未创建")
        return 1
    for r in rows:
        print(f"  P{r['partition']}  LEO={r['leo']:<5} committed={r['committed']:<5} lag={r['lag']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="多模态 RAG 解析 worker")
    p.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="常驻消费 Kafka")
    o = sub.add_parser("once", help="直接解析一个本地 PDF（不经过 Kafka）")
    o.add_argument("pdf")
    sub.add_parser("lag", help="查看消费堆积")
    sub.add_parser("topics", help="列出 topic")
    args = p.parse_args()

    _setup_log(args.log_level)
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    if args.cmd == "run":
        return run_forever()
    if args.cmd == "once":
        return run_once(args.pdf)
    if args.cmd == "lag":
        return show_lag()
    if args.cmd == "topics":
        for t in bus.list_topics():
            print(" ", t)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
