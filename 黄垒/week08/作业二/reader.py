"""网页正文抓取：抓取 HTML 抽正文；失败返回 None（调用方回退到 bocha summary）。"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CACHE_DIR = Path(__file__).resolve().parent / "cache" / "pages"
MAX_CHARS = 12000  # 单页送入模型的最大字符数，控制 token 消耗
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _cache_path(url: str) -> Path:
    return CACHE_DIR / f"{hashlib.md5(url.encode('utf-8')).hexdigest()}.txt"


def fetch_page(url: str, use_cache: bool = True, timeout: int = 25) -> str | None:
    """抓取并清洗单页正文；任何失败返回 None。"""
    cp = _cache_path(url)
    if use_cache and cp.exists():
        return cp.read_text(encoding="utf-8")
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = text.strip()
        if len(text) < 80:  # 疑似验证页/空页
            return None
        text = text[:MAX_CHARS]
        if use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cp.write_text(text, encoding="utf-8")
        return text
    except Exception:
        return None
