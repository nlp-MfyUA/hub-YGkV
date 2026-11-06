"""前端 API 客户端：封装对 FastAPI 后端的全部 HTTP 调用。

前端不 import sql_agent / eval 等任何核心包——前后端分离的边界就在这里：
本模块只依赖 requests，通过 HTTP + JSON 与后端通信。
"""
from __future__ import annotations

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class ApiError(RuntimeError):
    """后端不可用或返回错误时抛出，消息面向终端用户。"""


class SqlAgentApiClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 180.0):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    # ---------------------------------------------------------------- 内部
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _check(resp: requests.Response) -> dict:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise ApiError(f"后端返回 {resp.status_code}: {detail}")
        return resp.json()

    def _get(self, path: str) -> dict:
        try:
            resp = requests.get(self._url(path), timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(
                f"无法连接后端 {self.base_url}（{exc}）。\n\n"
                "请先在项目根目录启动后端：uvicorn backend.app:app --port 8000"
            ) from exc
        return self._check(resp)

    def _post(self, path: str, payload: dict | None = None) -> dict:
        try:
            resp = requests.post(self._url(path), json=payload or {},
                                 timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(
                f"无法连接后端 {self.base_url}（{exc}）。\n\n"
                "请先在项目根目录启动后端：uvicorn backend.app:app --port 8000"
            ) from exc
        return self._check(resp)

    # ---------------------------------------------------------------- 接口
    def health(self) -> dict:
        return self._get("/api/health")

    def schema(self) -> dict:
        return self._get("/api/schema")

    def query(self, question: str, *, max_attempts: int | None = None,
              summarize: bool | None = None) -> dict:
        payload: dict = {"question": question}
        if max_attempts is not None:
            payload["max_attempts"] = int(max_attempts)
        if summarize is not None:
            payload["summarize"] = bool(summarize)
        return self._post("/api/query", payload)

    def eval(self, ids: str | None = None) -> dict:
        return self._post("/api/eval", {"ids": ids})
