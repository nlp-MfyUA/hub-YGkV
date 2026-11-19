"""进程间通信：后端 -> 进程1 / 进程2，前端 -> 后端。都是 HTTP + JSON。"""

from __future__ import annotations

import time

import httpx

from . import config


class RpcError(RuntimeError):
    """下游进程调用失败（连不上 / 超时 / 返回非 2xx / 返回体不是 JSON）。"""


def post_json(base_url: str, path: str, payload: dict, *, timeout: float | None = None) -> dict:
    url = base_url.rstrip("/") + path
    try:
        with httpx.Client(timeout=timeout or config.RPC_TIMEOUT) as client:
            resp = client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RpcError(f"POST {url} 失败: {type(exc).__name__}: {exc}") from exc

    if resp.status_code >= 400:
        raise RpcError(f"POST {url} 返回 {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RpcError(f"POST {url} 返回体不是 JSON: {resp.text[:200]}") from exc


def post_json_with_retry(base_url: str, path: str, payload: dict, *, retry: int | None = None) -> dict:
    """重试一次就够：多半是下游刚启动或瞬时网络抖动，再多重试只是让用户干等。"""
    retry = config.RPC_RETRY if retry is None else retry
    last: Exception | None = None
    for attempt in range(retry + 1):
        try:
            return post_json(base_url, path, payload)
        except RpcError as exc:
            last = exc
            if attempt < retry:
                time.sleep(0.4 * (attempt + 1))
    raise RpcError(str(last))


def healthy(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(base_url.rstrip("/") + "/health")
        return resp.status_code == 200 and bool(resp.json().get("ok"))
    except Exception:  # noqa: BLE001 - 健康检查拿来判活，不该抛
        return False


def wait_until_healthy(targets: dict[str, str], timeout: float | None = None, quiet: bool = False) -> None:
    """等所有子进程起来。targets: {显示名: base_url}"""
    timeout = timeout or config.SERVICE_START_TIMEOUT
    deadline = time.time() + timeout
    pending = dict(targets)
    while pending and time.time() < deadline:
        for name, url in list(pending.items()):
            if healthy(url):
                pending.pop(name)
                if not quiet:
                    print(f"  ✓ {name} 就绪 {url}", flush=True)
        if pending:
            time.sleep(0.4)
    if pending:
        raise RpcError(f"等待超时（{timeout:.0f}s）：{', '.join(pending)}")


# --------------------------------------------------------------------------- #
# 异步版本（agents 版的后端是 async 的，用 httpx.AsyncClient 更省线程）
# --------------------------------------------------------------------------- #
async def post_json_async(base_url: str, path: str, payload: dict, *, timeout: float | None = None) -> dict:
    url = base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=timeout or config.RPC_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RpcError(f"POST {url} 失败: {type(exc).__name__}: {exc}") from exc
    if resp.status_code >= 400:
        raise RpcError(f"POST {url} 返回 {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RpcError(f"POST {url} 返回体不是 JSON: {resp.text[:200]}") from exc


async def post_json_async_with_retry(
    base_url: str, path: str, payload: dict, *, retry: int | None = None
) -> dict:
    import asyncio

    retry = config.RPC_RETRY if retry is None else retry
    last: Exception | None = None
    for attempt in range(retry + 1):
        try:
            return await post_json_async(base_url, path, payload)
        except RpcError as exc:
            last = exc
            if attempt < retry:
                await asyncio.sleep(0.4 * (attempt + 1))
    raise RpcError(str(last))
