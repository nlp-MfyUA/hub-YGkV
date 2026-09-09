"""博查(Bocha) Web 搜索客户端，带磁盘缓存。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

import llm

BOCHA_URL = "https://api.bocha.cn/v1/web-search"
DEFAULT_KEY = os.getenv("BOCHA_API_KEY", "")
CACHE_DIR = Path(__file__).resolve().parent / "cache" / "search"


def _api_key() -> str:
    llm.load_env()
    return os.getenv("BOCHA_API_KEY") or DEFAULT_KEY


def _cache_path(query: str, count: int, summary: bool) -> Path:
    raw = f"{query}|{count}|{summary}"
    return CACHE_DIR / f"{hashlib.md5(raw.encode('utf-8')).hexdigest()}.json"


def search(query: str, count: int = 8, summary: bool = True, use_cache: bool = True) -> list[dict]:
    """返回规范化结果列表，每项含 title/url/snippet/summary/siteName/datePublished。"""
    key = _api_key()
    if not key:
        raise RuntimeError("缺少 BOCHA_API_KEY，请在 .env 中配置")
    cp = _cache_path(query, count, summary)
    if use_cache and cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))

    payload = {"query": query, "summary": summary, "count": count}
    resp = requests.post(
        BOCHA_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 200:
        raise RuntimeError(f"bocha 搜索失败: {body.get('msg')} code={body.get('code')}")
    items = []
    for it in (body.get("data") or {}).get("webPages", {}).get("value", []):
        items.append(
            {
                "title": it.get("name", ""),
                "url": it.get("url", ""),
                "snippet": it.get("snippet", ""),
                "summary": it.get("summary", ""),
                "siteName": it.get("siteName", ""),
                "datePublished": it.get("datePublished", ""),
            }
        )
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    time.sleep(0.3)  # 轻微限速，避免触发频控
    return items
