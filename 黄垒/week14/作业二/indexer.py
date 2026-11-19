#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Elasticsearch 检索层。

用 REST（httpx）而不是官方 client：版本耦合最小，DSL 一眼看得见。
中文用 ik_max_word：`中华人民共和国` 会切成 `中华人民共和国 / 中华人民 / 中华 / 华人 / 人民共和国 …`，
比单字切分召回好很多。

关于「为什么没有向量检索」：机器上只有生成式 VLM（Qwen3.5-0.8B），没有 embedding 模型。
这里的接口是抽象的（search 只吐 chunk_id + score），要上向量只需要：
  1) 起一个 bge-m3 / text-embedding 服务；
  2) mapping 里加 dense_vector 字段；
  3) search 里加一个 knn 子句做混合打分。
图注文本是 VLM 生成的语义描述，本身已经承担了一部分「跨模态对齐」的作用。
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

import config

log = logging.getLogger("indexer")

_client: Optional[httpx.Client] = None


def _c() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=config.ES_URL, timeout=config.ES_TIMEOUT,
                               trust_env=False)   # 机器上有 HTTP_PROXY，ES 在本机，必须绕过
    return _client


MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "refresh_interval": "1s",
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "filename": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "page": {"type": "integer"},
            "idx": {"type": "integer"},
            "section": {"type": "text", "analyzer": "ik_max_word"},
            "body": {"type": "text", "analyzer": "ik_max_word"},
            "caption": {"type": "text", "analyzer": "ik_max_word"},
            "has_image": {"type": "boolean"},
        }
    },
}


# ---------------------------------------------------------------- 索引维护
def ensure_index() -> Dict[str, Any]:
    c = _c()
    r = c.head(f"/{config.ES_INDEX}")
    if r.status_code == 200:
        return {"created": False, "index": config.ES_INDEX}
    r = c.put(f"/{config.ES_INDEX}", json=MAPPING)
    if r.status_code >= 300:
        raise RuntimeError(f"创建索引失败 {r.status_code}: {r.text[:400]}")
    return {"created": True, "index": config.ES_INDEX}


def index_chunks(doc_id: str, filename: str, chunks: List[Dict[str, Any]]) -> int:
    """bulk 写入。分块表是源，ES 是索引，重灌一次即可。"""
    if not chunks:
        return 0
    lines: List[str] = []
    for ch in chunks:
        lines.append('{"index":{"_index":"%s","_id":"%s"}}' % (config.ES_INDEX, ch["id"]))
        body = {
            "chunk_id": ch["id"],
            "doc_id": doc_id,
            "filename": filename,
            "kind": ch["kind"],
            "page": ch.get("page") or 0,
            "idx": ch["idx"],
            "section": ch.get("section") or "",
            "body": ch.get("text") or "",
            "caption": ch.get("text") if ch["kind"] == "image" else "",
            "has_image": bool(ch.get("image_path")),
        }
        lines.append(json.dumps(body, ensure_ascii=False))
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    r = _c().post("/_bulk?refresh=true", content=payload,
                  headers={"Content-Type": "application/x-ndjson"})
    if r.status_code >= 300:
        raise RuntimeError(f"bulk 失败 {r.status_code}: {r.text[:400]}")
    data = r.json()
    if data.get("errors"):
        bad = [i for i in data["items"] if i.get("index", {}).get("error")][:2]
        raise RuntimeError(f"bulk 部分失败: {bad}")
    return len(chunks)


def delete_doc(doc_id: str) -> None:
    _c().post(f"/{config.ES_INDEX}/_delete_by_query?refresh=true",
              json={"query": {"term": {"doc_id": doc_id}}})


def reset_index() -> None:
    _c().delete(f"/{config.ES_INDEX}")
    ensure_index()


# ---------------------------------------------------------------- 检索
_VISUAL_HINTS = ("图", "表", "示意", "架构", "流程", "截图", "画", "chart", "figure", "table")


def search(query: str, top_k: int = 6, doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """BM25 召回 + 意图加权重排。doc_ids 非空时只在这些文档里检索。"""
    q = (query or "").strip()
    if not q:
        return []
    visual = any(h in q.lower() for h in _VISUAL_HINTS)
    should = [
        {"multi_match": {"query": q, "type": "best_fields",
                         "fields": ["body^1.0", "caption^2.2", "section^1.6"]}},
        {"match_phrase": {"body": {"query": q, "boost": 1.4, "slop": 2}}},
    ]
    inner: Dict[str, Any] = {"bool": {"should": should, "minimum_should_match": 1}}
    if doc_ids:
        inner = {"bool": {"must": [inner],
                          "filter": [{"terms": {"doc_id": list(doc_ids)}}]}}
    dsl: Dict[str, Any] = {
        "size": max(top_k * 4, 20),
        "query": {
            "function_score": {
                "query": inner,
                "functions": [
                    {"filter": {"term": {"kind": "image"}},
                     "weight": 2.0 if visual else 1.05},
                    {"filter": {"term": {"kind": "table"}},
                     "weight": 1.8 if visual else 1.0},
                ],
                "score_mode": "multiply",
                "boost_mode": "multiply",
            }
        },
        "_source": ["chunk_id", "doc_id", "filename", "kind", "page", "idx",
                    "section", "body", "caption"],
    }
    r = _c().post(f"/{config.ES_INDEX}/_search", json=dsl)
    if r.status_code >= 300:
        log.warning("ES 查询失败 %s: %s", r.status_code, r.text[:300])
        return []
    hits = r.json().get("hits", {}).get("hits", [])
    out: List[Dict[str, Any]] = []
    for h in hits:
        s = h["_source"]
        out.append({"chunk_id": s["chunk_id"], "score": round(float(h["_score"]), 4),
                    "doc_id": s["doc_id"], "filename": s["filename"],
                    "kind": s["kind"], "page": s.get("page"),
                    "section": s.get("section") or "",
                    "text": s.get("body") or ""})
    return out[:top_k]


def search_multi(queries: List[str], top_k: int,
                 doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """多路查询合并（原问题 + 关键词串），同一个 chunk 取最高分。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for q in queries:
        for hit in search(q, top_k, doc_ids):
            cur = merged.get(hit["chunk_id"])
            if cur is None or hit["score"] > cur["score"]:
                merged[hit["chunk_id"]] = hit
    return sorted(merged.values(), key=lambda x: -x["score"])


def best_visual(query: str, doc_id: Optional[str] = None,
                doc_ids: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """挑一条「最相关的图表块」。

    用途：问答要求图文混排，但纯文字问题（比如「五种范式是什么」）的 BM25 结果
    可能全是正文块。这时补一条图表证据，模型才有图可看、页面才有图可插。
    没有匹配词时按 match_all 兜底，保证一定拿得到同文档的图表。
    """
    must: List[Dict[str, Any]] = [{"terms": {"kind": ["image", "table"]}}]
    if doc_id:
        must.append({"term": {"doc_id": doc_id}})
    elif doc_ids:
        must.append({"terms": {"doc_id": list(doc_ids)}})
    dsl = {
        "size": 1,
        "query": {"bool": {
            "must": must,
            "should": [{"multi_match": {"query": query or "",
                                        "fields": ["body", "caption^2", "section"]}}],
            "minimum_should_match": 0,
        }},
        "_source": ["chunk_id", "doc_id", "filename", "kind", "page", "idx",
                    "section", "body", "caption"],
    }
    r = _c().post(f"/{config.ES_INDEX}/_search", json=dsl)
    if r.status_code >= 300:
        return None
    hits = r.json().get("hits", {}).get("hits", [])
    if not hits:
        return None
    s = hits[0]["_source"]
    return {"chunk_id": s["chunk_id"], "score": round(float(hits[0]["_score"]), 4),
            "doc_id": s["doc_id"], "filename": s["filename"], "kind": s["kind"],
            "page": s.get("page"), "section": s.get("section") or "",
            "text": s.get("body") or ""}


# ---------------------------------------------------------------- 观测
def health() -> Dict[str, Any]:
    try:
        c = _c()
        r = c.get("/_cluster/health")
        cnt = c.get(f"/{config.ES_INDEX}/_count")
        return {"ok": r.status_code == 200,
                "status": r.json().get("status") if r.status_code == 200 else "red",
                "docs": cnt.json().get("count") if cnt.status_code == 200 else None}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
