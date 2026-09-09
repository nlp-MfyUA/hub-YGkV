# -*- coding: utf-8 -*-
"""检索模块：封装 Bocha web-search API（普通函数，非 agent 工具），返回规范化 list[dict]。"""
from __future__ import annotations

import logging

import requests

from . import config

logger = logging.getLogger(__name__)


def _rows(data) -> list:
    """Bocha 真实形状：data.webPages.value = [item]。宽松兼容 list / 嵌套 dict。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        web_pages = data.get("webPages")
        if isinstance(web_pages, dict) and isinstance(web_pages.get("value"), list):
            return web_pages["value"]
        for key in ("results", "web_results", "value"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize(item: dict) -> dict:
    return {
        "title": item.get("name") or item.get("title") or "",
        "url": item.get("url") or "",
        "snippet": item.get("snippet") or item.get("summary") or "",
        "site_name": item.get("siteName") or item.get("site_name") or "",
        "date": item.get("datePublished") or item.get("date") or "",
    }


def web_search(query: str, count: int | None = None) -> list[dict]:
    """按关键词搜一次网页，返回 [{title, url, snippet, site_name, date}]。"""
    if not config.BOCHA_API_KEY:
        raise RuntimeError("未配置 BOCHA_API_KEY，请复制 .env.example 为 .env 并填入密钥")
    payload = {
        "query": query,
        "summary": True,
        "count": count or config.BOCHA_SEARCH_COUNT,
    }
    resp = requests.post(
        config.BOCHA_URL,
        headers={
            "Authorization": f"Bearer {config.BOCHA_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data")
    results = [_normalize(r) for r in _rows(data) if isinstance(r, dict)]
    logger.info("web_search「%s」→ %d 条", query, len(results))
    return results
