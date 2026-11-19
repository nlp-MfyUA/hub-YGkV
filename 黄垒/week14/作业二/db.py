#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MySQL 持久层：文档表 + 分块表。

为什么用 MySQL 而不是只靠 ES：
  · 状态机（待解析/解析中/已完成/失败）要能事务化更新，还要给前端轮询；
  · 分块是 ES 索引的「源数据」，重建索引时可以直接从表里回灌；
  · ES 只负责检索，MySQL 是事实来源（source of truth）。
"""

import hashlib
import json
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

import pymysql
from pymysql.cursors import DictCursor

import config

STATUS_PENDING = "PENDING"     # 待解析：已入库、消息已进 Kafka
STATUS_PARSING = "PARSING"     # 解析中
STATUS_DONE = "DONE"           # 解析完成
STATUS_FAILED = "FAILED"       # 解析失败（含重试用尽）

DDL_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS rag_documents (
  id            VARCHAR(32)  NOT NULL PRIMARY KEY,
  filename      VARCHAR(255) NOT NULL,
  size_bytes    BIGINT       NOT NULL DEFAULT 0,
  sha256        CHAR(64)     NOT NULL,
  status        VARCHAR(16)  NOT NULL DEFAULT 'PENDING',
  file_path     VARCHAR(512) NOT NULL,
  work_dir      VARCHAR(512) NULL,
  pages         INT          NOT NULL DEFAULT 0,
  n_chunks      INT          NOT NULL DEFAULT 0,
  n_images      INT          NOT NULL DEFAULT 0,
  attempts      INT          NOT NULL DEFAULT 0,
  parse_seconds FLOAT        NULL,
  engine        VARCHAR(32)  NULL,
  error         TEXT         NULL,
  created_at    DATETIME     NOT NULL,
  started_at    DATETIME     NULL,
  finished_at   DATETIME     NULL,
  UNIQUE KEY uk_sha256 (sha256),
  KEY k_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

DDL_CHUNKS = """
CREATE TABLE IF NOT EXISTS rag_chunks (
  id         VARCHAR(48)  NOT NULL PRIMARY KEY,
  doc_id     VARCHAR(32)  NOT NULL,
  idx        INT          NOT NULL,
  kind       VARCHAR(12)  NOT NULL,   -- text / image / table
  section    VARCHAR(255) NULL,       -- 所属章节标题路径
  text       MEDIUMTEXT   NULL,       -- 正文 或 图注/图题
  html       MEDIUMTEXT   NULL,       -- 表格 html
  image_path VARCHAR(512) NULL,       -- 图片在 media 下的相对路径
  page       INT          NULL,
  bbox       VARCHAR(80)  NULL,
  n_chars    INT          NOT NULL DEFAULT 0,
  KEY k_doc (doc_id, idx)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_SCHEMA = [DDL_DOCUMENTS, DDL_CHUNKS]


@contextmanager
def connect(with_db: bool = True):
    """每次调用取一条短连接。demo 规模够用，也避免长连接被 MySQL 掐断后的脏状态。"""
    kwargs = dict(config.MYSQL)
    if not with_db:
        kwargs.pop("database", None)
    conn = pymysql.connect(cursorclass=DictCursor, autocommit=True, **kwargs)
    try:
        yield conn
    finally:
        conn.close()


def init_database() -> None:
    """建库 + 建表（幂等）。"""
    db = config.MYSQL["database"]
    with connect(with_db=False) as c, c.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}` "
                    f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    with connect() as c, c.cursor() as cur:
        for ddl in _SCHEMA:
            cur.execute(ddl)


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def new_doc_id(sha: str) -> str:
    """文档 id 用「内容哈希前 12 位 + 时间后缀」，天然可读且不重复。"""
    return f"d{sha[:10]}{int(time.time()) % 100000:05d}"


# ---------------------------------------------------------------- 读
def list_documents(limit: int = 200) -> List[Dict[str, Any]]:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT * FROM rag_documents ORDER BY created_at DESC LIMIT %s", (limit,))
        return cur.fetchall()


def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT * FROM rag_documents WHERE id=%s", (doc_id,))
        return cur.fetchone()


def find_by_sha(sha: str) -> Optional[Dict[str, Any]]:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT * FROM rag_documents WHERE sha256=%s", (sha,))
        return cur.fetchone()


def chunks_of_doc(doc_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT * FROM rag_chunks WHERE doc_id=%s ORDER BY idx LIMIT %s",
                    (doc_id, limit))
        return cur.fetchall()


def chunks_by_ids(ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = list(ids)
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    with connect() as c, c.cursor() as cur:
        cur.execute(f"SELECT * FROM rag_chunks WHERE id IN ({ph})", ids)
        return {r["id"]: r for r in cur.fetchall()}


def all_chunks_for_reindex(limit: int = 20000) -> List[Dict[str, Any]]:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT c.*, d.filename FROM rag_chunks c "
                    "JOIN rag_documents d ON d.id=c.doc_id "
                    "WHERE d.status=%s ORDER BY c.doc_id, c.idx LIMIT %s",
                    (STATUS_DONE, limit))
        return cur.fetchall()


def stats() -> Dict[str, Any]:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT status, COUNT(*) n FROM rag_documents GROUP BY status")
        by_status = {r["status"]: r["n"] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) n, COALESCE(SUM(n_chars),0) ch FROM rag_chunks")
        row = cur.fetchone()
    return {"documents_by_status": by_status,
            "chunks": row["n"], "chunk_chars": int(row["ch"])}


# ---------------------------------------------------------------- 写
def create_document(doc_id: str, filename: str, size_bytes: int, sha: str,
                    file_path: str) -> Dict[str, Any]:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO rag_documents (id,filename,size_bytes,sha256,status,file_path,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (doc_id, filename, size_bytes, sha, STATUS_PENDING, file_path, now))
    return get_document(doc_id)


def mark_parsing(doc_id: str, work_dir: str) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE rag_documents SET status=%s, work_dir=%s, started_at=%s, "
            "attempts=attempts+1, error=NULL WHERE id=%s AND status<>%s",
            (STATUS_PARSING, work_dir, now, doc_id, STATUS_DONE))


def mark_done(doc_id: str, pages: int, n_chunks: int, n_images: int,
              seconds: float, engine: str) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE rag_documents SET status=%s, pages=%s, n_chunks=%s, n_images=%s, "
            "parse_seconds=%s, engine=%s, finished_at=%s, error=NULL WHERE id=%s",
            (STATUS_DONE, pages, n_chunks, n_images, seconds, engine, now, doc_id))


def mark_failed(doc_id: str, error: str) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as c, c.cursor() as cur:
        cur.execute("UPDATE rag_documents SET status=%s, error=%s, finished_at=%s WHERE id=%s",
                    (STATUS_FAILED, error[:4000], now, doc_id))


def reset_to_pending(doc_id: str, error: str) -> None:
    """重试投递前把状态退回「待解析」，前端能直接看到回退。"""
    with connect() as c, c.cursor() as cur:
        cur.execute("UPDATE rag_documents SET status=%s, error=%s WHERE id=%s",
                    (STATUS_PENDING, error[:2000], doc_id))


def replace_chunks(doc_id: str, chunks: List[Dict[str, Any]]) -> None:
    """整篇重写分块：先删后插，保证「重新解析」不会留下脏数据。"""
    rows = []
    for ch in chunks:
        rows.append((
            ch["id"], doc_id, ch["idx"], ch["kind"], ch.get("section"),
            ch.get("text"), ch.get("html"), ch.get("image_path"),
            ch.get("page"), ch.get("bbox"), len(ch.get("text") or ""),
        ))
    with connect() as c, c.cursor() as cur:
        cur.execute("DELETE FROM rag_chunks WHERE doc_id=%s", (doc_id,))
        if rows:
            cur.executemany(
                "INSERT INTO rag_chunks (id,doc_id,idx,kind,section,text,html,image_path,page,bbox,n_chars) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)


def delete_document(doc_id: str) -> None:
    with connect() as c, c.cursor() as cur:
        cur.execute("DELETE FROM rag_chunks WHERE doc_id=%s", (doc_id,))
        cur.execute("DELETE FROM rag_documents WHERE id=%s", (doc_id,))


def snapshot() -> str:
    """给 smoke_test 用的可读快照。"""
    return json.dumps(stats(), ensure_ascii=False)
