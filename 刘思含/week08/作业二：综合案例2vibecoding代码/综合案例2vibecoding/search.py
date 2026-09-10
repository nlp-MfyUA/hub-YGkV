# -*- coding: utf-8 -*-
"""search —— Bocha 网页搜索工具，研究循环的检索环节。"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

API_KEY = os.environ.get("BOCHA_API_KEY", "")
COUNT = int(os.environ.get("BOCHA_SEARCH_COUNT", "5"))


async def web_search(query: str) -> list[dict]:
    """搜索一个关键词，返回结果列表（title / url / snippet / site_name / date）。"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.bocha.cn/v1/web-search",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={"query": query, "summary": True, "count": COUNT},
        )
        resp.raise_for_status()
        data = resp.json()

    pages = data.get("data", {}).get("webPages", {}).get("value", [])
    return [
        {
            "title": p.get("name") or "",
            "url": p.get("url") or "",
            "snippet": (p.get("snippet") or p.get("summary") or "")[:500],
            "site_name": p.get("siteName") or "",
            "date": p.get("datePublished") or "",
        }
        for p in pages
    ]
