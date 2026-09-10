import asyncio
import ipaddress
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import trafilatura


class RetrievalError(Exception):
    pass


class TransientRetrievalError(RetrievalError):
    pass


class UnsafeURL(RetrievalError):
    pass


def normalize_url(raw: str) -> str:
    try:
        url = httpx.URL(raw)
        if url.scheme not in ("http", "https") or not url.host or url.userinfo:
            raise ValueError
        if url.port not in (None, 80, 443):
            raise ValueError
        host = url.host.lower().rstrip(".")
        if "%" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError
        return str(url.copy_with(host=host, fragment=None))
    except (ValueError, httpx.InvalidURL):
        raise UnsafeURL("仅允许无凭据的公开 HTTP(S) 网页和标准端口") from None


async def public_addresses(host: str, port: int) -> list[str]:
    try:
        # 校验所有解析结果，而不是只检查字符串或首个地址。
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise TransientRetrievalError("域名解析失败") from None
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise TransientRetrievalError("域名无可用地址")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise UnsafeURL("拒绝访问非公开网络地址")
        if isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo):
            raise UnsafeURL("拒绝 IPv6 地址转换目标")
    return addresses


class PublicTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport(retries=0, limits=httpx.Limits(max_keepalive_connections=0))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = httpx.URL(normalize_url(str(request.url)))
        addresses = await public_addresses(url.host, url.port or (443 if url.scheme == "https" else 80))
        # 连接固定到已验证 IP，保留原 Host 和 TLS SNI，避免 DNS 重绑定。
        headers = request.headers.copy()
        headers["Host"] = url.netloc.decode("ascii")
        pinned = httpx.Request(
            request.method, url.copy_with(host=addresses[0]), headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": url.host},
        )
        return await self.inner.handle_async_request(pinned)

    async def aclose(self):
        await self.inner.aclose()


@dataclass
class Page:
    url: str
    title: str
    text: str
    published_at: str | None


class WebReader:
    MAX_BYTES = 2 * 1024 * 1024

    def __init__(self, transport=None):
        self.client = httpx.AsyncClient(
            transport=transport or PublicTransport(), trust_env=False,
            timeout=12, follow_redirects=False,
            headers={"User-Agent": "LocalResearchAssistant/0.1", "Accept": "text/html,application/xhtml+xml"},
        )

    async def read(self, raw_url: str) -> Page:
        url = normalize_url(raw_url)
        try:
            for _ in range(6):
                async with self.client.stream("GET", url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise RetrievalError("重定向缺少目标")
                        url = normalize_url(str(response.url.join(location)))
                        continue
                    if response.status_code == 429 or response.status_code >= 500:
                        raise TransientRetrievalError(f"网页暂不可用（HTTP {response.status_code}）")
                    if response.status_code >= 400:
                        raise RetrievalError(f"网页拒绝访问（HTTP {response.status_code}）")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if content_type not in ("text/html", "application/xhtml+xml"):
                        raise RetrievalError("跳过非 HTML 内容")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > self.MAX_BYTES:
                            raise RetrievalError("网页超过 2 MiB 限制")
                page = await asyncio.to_thread(self.extract, bytes(chunks), url)
                if not page.text.strip():
                    raise RetrievalError("网页没有可读取正文")
                return page
            raise RetrievalError("重定向次数过多")
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            raise TransientRetrievalError("网页网络异常") from None

    @staticmethod
    def extract(html: bytes, url: str) -> Page:
        doc = trafilatura.bare_extraction(
            html, url=url, include_comments=False, include_tables=True, with_metadata=True,
            date_extraction_params={"original_date": True, "extensive_search": False},
        )
        if doc is None:
            raise RetrievalError("网页正文抽取为空")
        return Page(url=url, title=doc.title or urlsplit(url).hostname or url,
                    text=(doc.text or "")[:14000], published_at=doc.date or None)

    async def close(self):
        await self.client.aclose()


class Search:
    async def search(self, query: str) -> list[dict]:
        env = os.environ.copy()
        env.pop("DEEPSEEK_API_KEY", None)
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "research_assistant.search_worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env, **options,
        )
        try:
            async with asyncio.timeout(18):
                stdout, _ = await process.communicate(json.dumps({"query": query}).encode("utf-8"))
            if process.returncode:
                raise RetrievalError("检索进程失败")
            data = json.loads(stdout)
            if "error" in data:
                error_type = TransientRetrievalError if data.get("transient") else RetrievalError
                raise error_type(data["error"])
            return data["results"][:5]
        except TimeoutError:
            raise TransientRetrievalError("检索超时") from None
        except (ValueError, KeyError):
            raise RetrievalError("检索返回格式异常") from None
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
