"""博查（Bocha）Web 搜索封装。API Key 放服务端配置（.env BOCHA_API_KEY），不写进代码/前端。"""
import os

import httpx

BOCHA_API_KEY = os.environ.get("BOCHA_API_KEY", "")
BOCHA_URL = "https://api.bocha.cn/v1/web-search"


class BochaError(Exception):
    pass


def web_search(query: str, count: int = 5) -> list[dict]:
    """返回 [{title, url, summary, date}]，summary=true 走博查摘要作为抽取输入。"""
    if not BOCHA_API_KEY:
        raise BochaError("未配置 BOCHA_API_KEY")
    resp = httpx.post(
        BOCHA_URL,
        json={"query": query, "summary": True, "count": count},
        headers={"Authorization": f"Bearer {BOCHA_API_KEY}", "Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = (data.get("data") or {}).get("webPages", {}).get("value") or []
    out = []
    for item in results:
        out.append({
            "title": item.get("name", ""),
            "url": item.get("url", ""),
            "summary": item.get("summary") or item.get("snippet", ""),
            "date": item.get("datePublished", ""),
        })
    return out
