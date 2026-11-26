#!/usr/bin/env python3
"""Read public search responses. Results are discovery leads, never evidence.

No login, CAPTCHA solving, cookie import, or browser-registration repair is used.
Blocked engines are not retried during the same process. HTML structure and a
limited lexical response check are reported separately from research relevance.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ENGINES = ("sogou", "360", "bing", "duckduckgo", "google")
_BLOCKED_IN_PROCESS: set[str] = set()
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    parent: "Node | None" = None
    children: list["Node | str"] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        if self.tag in ("script", "style", "noscript"):
            return ""
        return " ".join(item if isinstance(item, str) else item.text() for item in self.children)

    def descendants(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()


class TreeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _clean(text: str, limit: int = 1400) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()[:limit]


def _plain(text: str) -> str:
    parser = TreeParser()
    parser.feed(text)
    return _clean(parser.root.text())


def _url(value: str, base_url: str) -> str | None:
    value = unescape(value or "").strip()
    if any(char in value for char in "\r\n\x00"):
        return None
    absolute = urllib.parse.urljoin(base_url, value)
    try:
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return None
        query = urllib.parse.parse_qs(parsed.query)
        decoded = query.get("uddg", [None])[0]
        if parsed.path == "/url":
            decoded = query.get("q", query.get("url", [None]))[0]
        if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/"):
            encoded = query.get("u", [""])[0]
            if encoded.startswith("a1"):
                try:
                    encoded = encoded[2:]
                    decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
                except (ValueError, UnicodeError):
                    pass
        if decoded and decoded.startswith(("https://", "http://")):
            return _url(decoded, "")
        if parsed.path == "/search" and parsed.hostname.endswith(("google.com", "bing.com")):
            return None
        if parsed.hostname == "ai.so.com" and parsed.path.startswith("/search"):
            return None  # Provider-generated answer card, not an original result page.
        return absolute
    except ValueError:
        return None


def _container(node: Node, engine: str) -> Node:
    current = node
    classes = {"sogou": {"vrwrap", "rb", "results"}, "360": {"res-list"},
               "bing": {"b_algo"}, "duckduckgo": {"result"},
               "google": {"g", "MjjYud", "Gx5Zad"}}[engine]
    while current.parent is not None:
        if current.classes() & classes:
            return current
        current = current.parent
    return node.parent or node


def _snippet(container: Node, engine: str) -> str:
    classes = {"sogou": {"str_info", "str-info", "str_div", "text-layout", "star-wiki"},
               "360": {"res-desc", "res-comm-con", "res-rich", "mh-detail"},
               "bing": {"b_caption"}, "duckduckgo": {"result__snippet"},
               "google": {"VwiC3b", "BNeawe", "IsZvec"}}[engine]
    nodes = list(container.descendants())
    for node in nodes:
        if node.classes() & classes:
            return _clean(node.text())
    for node in nodes:
        if node.tag == "p":
            return _clean(node.text())
    return ""


def _unique(results: list[dict]) -> list[dict]:
    seen, output = set(), []
    for result in results:
        key = urllib.parse.urldefrag(result["url"])[0]
        if key not in seen and result["title"]:
            seen.add(key)
            output.append(result)
    return output


def parse_rss(body: str) -> list[dict]:
    tree = ET.fromstring(body)
    results = []
    for item in tree.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in item}
        url = _url(fields.get("link", ""), "https://www.bing.com")
        if url:
            results.append({"title": _plain(fields.get("title", "")), "url": url,
                            "snippet": _plain(fields.get("description", ""))})
    return _unique(results)


def parse_html(engine: str, body: str, base_url: str) -> list[dict]:
    parser = TreeParser()
    parser.feed(body)
    results = []
    for node in parser.root.descendants():
        anchor = None
        if engine == "duckduckgo" and node.tag == "a" and node.classes() & {"result__a", "result-link"}:
            anchor = node
        elif engine == "sogou" and node.tag == "h3" and "vr-title" in node.classes():
            anchor = next((child for child in node.descendants() if child.tag == "a"), None)
        elif engine in ("360", "bing") and node.tag in ("h2", "h3"):
            container = _container(node, engine)
            if not container.classes() & ({"res-list"} if engine == "360" else {"b_algo"}):
                continue
            anchor = next((child for child in node.descendants() if child.tag == "a"), None)
        elif engine == "google" and node.tag == "h3":
            current = node.parent
            while current is not None and current.tag != "a":
                current = current.parent
            anchor = current
        if anchor is None:
            continue
        observed = anchor.attrs.get("data-mdurl") or anchor.attrs.get("href", "")
        url = _url(observed, base_url)
        if url:
            results.append({"title": _clean(node.text()), "url": url,
                            "snippet": _snippet(_container(node, engine), engine)})
    return _unique(results)


def parse_response(engine: str, body: str, base_url: str, query: str = "") -> dict:
    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", body, re.I | re.S)
    title = _plain(title_match.group(1)) if title_match else ""
    title_lower = title.lower()
    blocked = any(term in title_lower for term in ("安全验证", "验证码", "人机验证", "access denied", "robot check"))
    blocked = blocked or any(term in body.lower() for term in (
        'id="challenge-form"', "unusual traffic from your computer network",
        "验证码确认不是自动程序", "请输入验证码以确认", "bots use duckduckgo"))
    observed_url = urllib.parse.urlsplit(base_url)
    challenge_host = observed_url.hostname or ""
    blocked = blocked or "captcha" in challenge_host.lower() or "antispider" in challenge_host.lower()
    if blocked or "/sorry/" in observed_url.path or "/captcha" in observed_url.path:
        return {"status": "blocked", "results": [], "warnings": ["Search provider requires verification; no bypass attempted"]}
    try:
        results = parse_rss(body) if engine == "bing" and re.search(r"<(?:\w+:)?rss\b", body[:1000], re.I) else parse_html(engine, body, base_url)
    except (ET.ParseError, ValueError, RecursionError):
        return {"status": "parse_failed", "results": [], "warnings": ["Search response structure could not be parsed"]}
    if not results:
        if engine == "google" and ("enablejs" in body or "enable javascript" in body.lower()):
            return {"status": "javascript_required", "results": [], "warnings": ["Provider returned a JavaScript-only entry page"]}
        no_results = re.search(r"没有找到|未找到相关|无相关结果|no results found|did not match any documents", body, re.I)
        return {"status": "no_results" if no_results else "parse_failed", "results": [],
                "warnings": [] if no_results else ["No supported result blocks found; this is not evidence of no matches"]}
    warnings = []
    text = " ".join(result["title"] + " " + result["snippet"] for result in results).lower()
    sites = re.findall(r"\bsite:([A-Za-z0-9.-]+)", query, re.I)
    if sites and not any(any((urllib.parse.urlsplit(result["url"]).hostname or "").lower() == site.lower()
                        or (urllib.parse.urlsplit(result["url"]).hostname or "").lower().endswith("." + site.lower())
                        for site in sites) for result in results):
        warnings.append("Requested site filter is not reflected in the observed result URLs")
    remaining = re.sub(r"\bsite:\S+", "", query)
    terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", remaining)
    terms = [term.lower() for term in terms if term.lower() not in {"and", "the", "for", "with", "from", "http", "https", "www", "com"}]
    compact = re.sub(r"\s+", "", text)
    if terms and not any(term in text or (re.search(r"[\u4e00-\u9fff]", term) and term in compact) for term in terms):
        warnings.append("No substantive query token appears in returned titles/snippets")
    return {"status": "query_mismatch" if warnings else "ok", "results": results,
            "warnings": warnings}


def _request_url(engine: str, query: str) -> str:
    endpoints = {
        "sogou": ("https://www.sogou.com/web", {"query": query}),
        "360": ("https://www.so.com/s", {"q": query}),
        "bing": ("https://www.bing.com/search", {"q": query, "format": "rss", "mkt": "zh-CN"}),
        "duckduckgo": ("https://html.duckduckgo.com/html/", {"q": query}),
        "google": ("https://www.google.com/search", {"q": query, "gbv": "1", "num": "10"}),
    }
    url, parameters = endpoints[engine]
    return url + "?" + urllib.parse.urlencode(parameters)


def fetch_url(url: str, proxy: str | None, timeout: int) -> dict:
    proxies = {}
    if proxy:
        parsed = urllib.parse.urlsplit(proxy)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Proxy must be an HTTP(S) URL without inline credentials")
        proxies = {"http": proxy, "https": proxy}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    request = urllib.request.Request(url, headers={"User-Agent": "CodexESGResearch/1.0",
                "Accept": "text/html,application/rss+xml,application/xml;q=0.9", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2_500_001)
            if len(raw) > 2_500_000:
                return {"status": "response_too_large", "http_status": response.status, "final_url": response.url, "body": ""}
            charset = response.headers.get_content_charset()
            if not charset:
                match = re.search(br"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", raw[:4096], re.I)
                charset = match.group(1).decode("ascii") if match else "utf-8"
            try:
                body = raw.decode(charset, errors="replace")
            except LookupError:
                body = raw.decode("utf-8", errors="replace")
            return {"status": "fetched", "http_status": response.status, "final_url": response.url, "body": body}
    except urllib.error.HTTPError as error:
        raw = error.read(65536)
        return {"status": "http_error", "http_status": error.code,
                "final_url": error.url, "body": raw.decode("utf-8", errors="replace")}
    except (urllib.error.URLError, OSError, TimeoutError):
        return {"status": "network_error", "http_status": None, "final_url": url, "body": ""}


def search(query: str, engine: str = "auto", limit: int = 10, proxy: str | None = None,
           timeout: int = 10, *, fetcher=fetch_url) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("A nonempty search query is required")
    if engine not in ("auto", *ENGINES) or not 1 <= limit <= 50 or not 1 <= timeout <= 30:
        raise ValueError("Invalid engine, result limit, or timeout")
    query = query.strip()
    order = ("sogou", "360", "bing", "duckduckgo", "google") if re.search(r"[\u4e00-\u9fff]", query) else ("bing", "duckduckgo", "google", "sogou", "360")
    order = order if engine == "auto" else (engine,)
    attempts, best = [], None
    for candidate in order:
        url = _request_url(candidate, query)
        if candidate in _BLOCKED_IN_PROCESS:
            parsed = {"status": "blocked", "results": [], "warnings": ["Engine already required verification in this process; skipped"]}
            response = {"http_status": None, "final_url": url}
        else:
            response = fetcher(url, proxy, timeout)
            if response["status"] in ("network_error", "response_too_large"):
                parsed = {"status": response["status"], "results": [], "warnings": ["Search transport did not provide a usable response"]}
            else:
                parsed = parse_response(candidate, response.get("body", ""), response.get("final_url", url), query)
                if response["status"] == "http_error" and parsed["status"] != "blocked":
                    parsed = {"status": "http_error", "results": [], "warnings": ["Provider returned an HTTP error"]}
        if parsed["status"] == "blocked":
            _BLOCKED_IN_PROCESS.add(candidate)
            # Verification URLs can contain a per-session challenge token.
            final = urllib.parse.urlsplit(response.get("final_url", url))
            response["final_url"] = urllib.parse.urlunsplit(final._replace(query="", fragment=""))
        attempt = {"engine": candidate, "status": parsed["status"], "http_status": response.get("http_status"),
                   "search_url": url, "final_url": response.get("final_url", url),
                   "result_count": len(parsed["results"]), "warnings": parsed["warnings"]}
        attempts.append(attempt)
        entry = {"engine": candidate, **parsed}
        if best is None or len(entry["results"]) > len(best["results"]):
            best = entry
        if parsed["status"] == "ok":
            best = entry
            break
    assert best is not None
    return {"query": query, "queried_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "engine": best["engine"], "status": best["status"], "results": best["results"][:limit],
            "warnings": best["warnings"], "attempts": attempts,
            "usage": "discovery_only; read original documents and judge relevance before reporting"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--engine", choices=("auto", *ENGINES), default="auto")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--proxy", help="Optional existing HTTP(S) proxy; no credential values in the URL")
    parser.add_argument("--timeout", type=int, default=10)
    arguments = parser.parse_args()
    try:
        result = search(arguments.query, arguments.engine, arguments.limit, arguments.proxy, arguments.timeout)
    except ValueError as error:
        parser.error(str(error))
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(serialized)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
