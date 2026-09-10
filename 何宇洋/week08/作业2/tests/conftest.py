import pytest
import httpx


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """默认测试禁止真实 HTTP 传输，MockTransport 及伪依赖不受影响。"""
    def blocked(*args, **kwargs):
        raise AssertionError("离线测试不允许真实网络调用")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
