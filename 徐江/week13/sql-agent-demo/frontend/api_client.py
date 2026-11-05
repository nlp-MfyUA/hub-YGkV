"""前端 API 客户端：封装对 FastAPI 后端的全部 HTTP 调用。

前端不 import sql_agent / eval 等任何核心包——前后端分离的边界就在这里：
本模块只依赖 requests，通过 HTTP + JSON 与后端通信。

week13 起后端由 LangGraph 驱动，新增两类调用：
- query_stream()：消费 POST /api/query/stream 的 SSE 事件流，
  逐节点产出 (event, data)，event ∈ start / node / result / error；
- graph() / state()：LangGraph 图内省（Mermaid）与线程状态回查。
"""
from __future__ import annotations

import json
from typing import Iterator

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
              summarize: bool | None = None,
              thread_id: str | None = None) -> dict:
        payload: dict = {"question": question}
        if max_attempts is not None:
            payload["max_attempts"] = int(max_attempts)
        if summarize is not None:
            payload["summarize"] = bool(summarize)
        if thread_id is not None:
            payload["thread_id"] = thread_id
        return self._post("/api/query", payload)

    def eval(self, ids: str | None = None) -> dict:
        return self._post("/api/eval", {"ids": ids})

    def graph(self) -> dict:
        """LangGraph 状态机的 Mermaid 图。"""
        return self._get("/api/graph")

    def state(self, thread_id: str) -> dict | None:
        """回查某次运行的状态；不存在时返回 None。"""
        try:
            resp = requests.get(self._url(f"/api/state/{thread_id}"),
                                timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(
                f"无法连接后端 {self.base_url}（{exc}）。"
            ) from exc
        if resp.status_code == 404:
            return None
        return self._check(resp)

    # ---------------------------------------------------------------- 流式
    def query_stream(self, question: str, *, max_attempts: int | None = None,
                     summarize: bool | None = None,
                     thread_id: str | None = None) -> Iterator[tuple[str, dict]]:
        """SSE 流式运行工作流，逐事件产出 (event, data)。

        event ∈ {"start", "node", "result", "error"}：
        - start:  {"thread_id": ...}
        - node:   {"node": 节点名, "update": 该节点的 state 增量}
        - result: {"thread_id": ..., "result": 与 /api/query 一致的完整结果}
        - error:  {"detail": 错误信息}

        连接失败 / 非 2xx 抛出 ApiError；流开始后服务端出错以 error 事件交付。
        """
        payload: dict = {"question": question}
        if max_attempts is not None:
            payload["max_attempts"] = int(max_attempts)
        if summarize is not None:
            payload["summarize"] = bool(summarize)
        if thread_id is not None:
            payload["thread_id"] = thread_id
        try:
            resp = requests.post(self._url("/api/query/stream"), json=payload,
                                 stream=True, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(
                f"无法连接后端 {self.base_url}（{exc}）。\n\n"
                "请先在项目根目录启动后端：uvicorn backend.app:app --port 8000"
            ) from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            resp.close()
            raise ApiError(f"后端返回 {resp.status_code}: {detail}")

        event_name = ""
        try:
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if raw.startswith("event:"):
                    event_name = raw[len("event:"):].strip()
                elif raw.startswith("data:"):
                    body = raw[len("data:"):].strip()
                    if event_name:
                        try:
                            data = json.loads(body)
                        except ValueError:
                            data = {"raw": body}
                        yield event_name, data
                        event_name = ""
        finally:
            resp.close()
