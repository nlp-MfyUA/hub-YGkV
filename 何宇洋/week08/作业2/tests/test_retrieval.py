import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from research_assistant.retrieval import (PublicTransport, RetrievalError, Search, UnsafeURL,
                                          WebReader, normalize_url, public_addresses)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/a", "http://localhost/",
                                     "http://a.local/", "https://user:password@example.com/", "http://example.com:8080/",
                                     "http://[fe80::1%25eth0]/"])
def test_unsafe_url_syntax(url):
    with pytest.raises(UnsafeURL):
        normalize_url(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.1.1", "0.0.0.0",
                                    "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1"])
def test_private_dns_addresses_rejected(ip, monkeypatch):
    async def scenario():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]))
        with pytest.raises(UnsafeURL):
            await public_addresses("example.com", 80)
    asyncio.run(scenario())


def test_mixed_public_private_dns_rejected(monkeypatch):
    async def scenario():
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)) for ip in ["8.8.8.8", "127.0.0.1"]]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=infos))
        with pytest.raises(UnsafeURL):
            await public_addresses("example.com", 80)
    asyncio.run(scenario())


def test_transport_pins_ip_preserving_tls_hostname(monkeypatch):
    async def scenario():
        monkeypatch.setattr("research_assistant.retrieval.public_addresses", AsyncMock(return_value=["8.8.8.8"]))
        transport = PublicTransport()
        received = []
        async def handler(request):
            received.append(request)
            return httpx.Response(200, text="ok")
        transport.inner = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://example.com/page")
        assert received[0].url.host == "8.8.8.8"
        assert received[0].headers["host"] == "example.com"
        assert received[0].extensions["sni_hostname"] == "example.com"
    asyncio.run(scenario())


def test_redirect_to_private_ip_rejected(monkeypatch):
    async def scenario():
        async def addresses(host, port):
            if host == "127.0.0.1":
                raise UnsafeURL("拒绝访问非公开网络地址")
            return ["8.8.8.8"]
        monkeypatch.setattr("research_assistant.retrieval.public_addresses", addresses)
        transport = PublicTransport()
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        transport.inner = httpx.MockTransport(handler)
        reader = WebReader(transport)
        try:
            with pytest.raises(UnsafeURL):
                await reader.read("https://example.com/start")
            assert len(requests) == 1
        finally:
            await reader.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"), "非 HTML"),
    (httpx.Response(403), "拒绝访问"),
    (httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>"), "正文"),
    (httpx.Response(200, headers={"content-type": "text/html"}, content=b"a"*(2*1024*1024+1)), "2 MiB"),
])
def test_unreadable_pages(response, expected):
    async def scenario():
        reader = WebReader(httpx.MockTransport(lambda _: response))
        try:
            with pytest.raises(RetrievalError, match=expected):
                await reader.read("https://example.com/")
        finally:
            await reader.close()
    asyncio.run(scenario())


def test_actual_html_extraction():
    paragraph = "This is a public research article with detailed evidence about renewable energy and electricity production. " * 8
    html = f'<html><head><title>Research article</title></head><body><article><h1>Research article</h1><p>{paragraph}</p></article></body></html>'
    page = WebReader.extract(html.encode(), "https://example.com/article")
    assert "renewable energy" in page.text
    assert page.title == "Research article"
    assert page.published_at is None


def test_url_deduplication():
    assert normalize_url("https://EXAMPLE.com:443/article#anchor") == "https://example.com/article"


def test_cancel_search_kills_worker_and_does_not_inherit_key(monkeypatch):
    async def scenario():
        class Process:
            returncode = None
            killed = False
            waited = False

            async def communicate(self, data):
                await asyncio.sleep(30)

            def kill(self):
                self.killed = True
                self.returncode = -1

            async def wait(self):
                self.waited = True
                return self.returncode

        process = Process()
        spawn = AsyncMock(return_value=process)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-private-key")
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(Search().search("query"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.killed and process.waited
        assert "DEEPSEEK_API_KEY" not in spawn.call_args.kwargs["env"]
    asyncio.run(scenario())
