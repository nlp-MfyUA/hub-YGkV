"""HTTP client for MinerU 4.x file-parse server."""
import asyncio
import base64
import io
import logging
import zipfile
from pathlib import Path

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MOCK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAeUlEQVR4nO3PQQkAMAzAwCqpf1ETMxF7HINABFzm7H7dcEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFj13PLIEAOXyUUwAAAABJRU5ErkJggg=="
)


def _mock_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("markdown.md", "# 模拟文档\n\n这是 MinerU mock 输出，用于离线联调。\n\n![模拟图片](images/mock.png)\n")
        zf.writestr("images/mock.png", MOCK_PNG)
    return buf.getvalue()


async def parse_pdf(path: Path, tier: str | None = None) -> bytes:
    if settings.mineru_mock:
        await asyncio.sleep(0.2)
        return _mock_zip()
    base = settings.mineru_url.rstrip("/")
    tier = tier or settings.mineru_tier
    timeout = settings.mineru_timeout
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        with path.open("rb") as fh:
            resp = await client.post(
                f"{base}/v1/file_parse",
                files={"file": (path.name, fh, "application/pdf")},
                data={"tier": tier, "output_formats": "default", "wait_timeout": "3600"},
            )
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 202:
            payload = resp.json()
            status_url = payload.get("status_url")
            if not status_url:
                raise RuntimeError(f"MinerU 202 缺少 status_url: {payload}")
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(2)
                status = (await client.get(status_url)).json()
                if status.get("status") == "completed" and status.get("result_url"):
                    result = await client.get(status["result_url"])
                    result.raise_for_status()
                    return result.content
                if status.get("status") in {"failed", "canceled", "submission_unknown"}:
                    raise RuntimeError(f"MinerU 解析失败: {status.get('error') or status}")
            raise TimeoutError("MinerU 解析等待超时")
        raise RuntimeError(f"MinerU HTTP {resp.status_code}: {resp.text[:500]}")
