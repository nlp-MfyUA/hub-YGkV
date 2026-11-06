"""LLM 客户端。

- DeepSeekClient：调用 DeepSeek（OpenAI 兼容）真实 API，带网络层重试；
- MockClient：离线模拟客户端，用于没有 API Key 时验证工作流全链路。

两者实现同一接口：
    chat(messages, *, task="", temperature=None, max_tokens=None) -> LLMResponse

task 参数只有 MockClient 使用（用于分派到对应的模拟逻辑），真实客户端忽略它。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from .config import LLMConfig
from .prompts import extract_sql


class LLMError(RuntimeError):
    """LLM 调用失败。"""


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0


class BaseLLMClient:
    """客户端接口。"""

    model: str = ""

    def chat(
        self,
        messages: list[dict],
        *,
        task: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError


# ====================================================================== 真实 API
class DeepSeekClient(BaseLLMClient):
    """DeepSeek（OpenAI 兼容协议）客户端。"""

    def __init__(self, cfg: LLMConfig):
        if not cfg.api_key:
            raise LLMError(
                "未配置 API Key。请编辑 config.local.yaml，在 llm.api_key 处填入 "
                "DeepSeek Key（或设置环境变量 LLM_API_KEY）。"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMError("缺少依赖 openai，请先执行: pip install -r requirements.txt") from exc
        self._cfg = cfg
        self.model = cfg.model
        self._client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout_seconds,
            max_retries=0,  # 重试由本类自行控制，方便统一记录
        )

    def chat(self, messages, *, task="", temperature=None, max_tokens=None) -> LLMResponse:
        last_exc: Exception | None = None
        for attempt in range(self._cfg.net_max_retries + 1):
            start = time.monotonic()
            try:
                resp = self._client.chat.completions.create(
                    model=self._cfg.model,
                    messages=messages,
                    temperature=self._cfg.temperature if temperature is None else temperature,
                    max_tokens=self._cfg.max_tokens if max_tokens is None else max_tokens,
                )
                usage = resp.usage
                return LLMResponse(
                    content=resp.choices[0].message.content or "",
                    model=resp.model or self._cfg.model,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            except Exception as exc:  # noqa: BLE001 - 统一转成 LLMError 上报
                last_exc = exc
                if not _is_retryable(exc) or attempt == self._cfg.net_max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM 调用失败（{type(last_exc).__name__}）: {last_exc}") from last_exc


def _is_retryable(exc: Exception) -> bool:
    """限流 / 超时 / 5xx 才重试，鉴权失败、请求非法不重试。"""
    name = type(exc).__name__
    if name in {"RateLimitError", "APITimeoutError", "APIConnectionError",
                "InternalServerError", "APIStatusError"}:
        status = getattr(exc, "status_code", None)
        if name == "APIStatusError" and isinstance(status, int) and status < 500:
            return False
        return True
    return False


# ====================================================================== 离线模拟
def _normalize(text: str) -> str:
    return re.sub(r"[\s，。？！、,.?!]+", "", text)


class MockClient(BaseLLMClient):
    """离线模拟客户端：按 task 分派，用固定规则模拟 LLM 的各阶段输出。

    用途：
    1. 没有 API Key 时也能把「数据库解析 → 选表 → 生成 → 校验 → 改写 → 执行 → 汇总」
       整条链路跑通，验证代码与报告；
    2. 内置一个「首次故意写错列名」的用例（Q8），用来演示 校验失败 → 改写 → 重试 回路。

    切换到真实模型只需在配置里填入 Key 并将 provider 改为 deepseek。
    """

    # 问题（归一化后）-> 选中的表
    _TABLES: dict[str, list[str]] = {}

    # 问题（归一化后）-> 正确 SQL
    _SQL: dict[str, str] = {}

    # 问题（归一化后）-> 首次生成时故意埋下的错误 SQL（用于演示改写回路）
    _FIRST_ATTEMPT_BUGS: dict[str, str] = {}

    # 常见列名错误 -> 正确列名（改写阶段依据报错信息修复）
    _COLUMN_FIXES = {
        "orders.amount": "orders.total_amount",
        "orders.total": "orders.total_amount",
        "users.name": "users.user_name",
        "products.name": "products.product_name",
        "orders.date": "orders.order_date",
        "order.date": "orders.order_date",
    }

    def __init__(self, model: str = "mock-offline"):
        self.model = model

    # ---------------------------------------------------------------- 接口
    def chat(self, messages, *, task="", temperature=None, max_tokens=None) -> LLMResponse:
        user_text = _last_user_text(messages)
        if task == "select_tables":
            content = self._select_tables(user_text)
        elif task == "generate_sql":
            content = self._generate_sql(user_text)
        elif task == "rewrite_sql":
            content = self._rewrite_sql(user_text)
        elif task == "summarize":
            content = self._summarize(user_text)
        else:
            content = "（mock 客户端）未识别的任务类型。"
        return LLMResponse(content=content, model=self.model)

    # ------------------------------------------------------------ 各任务模拟
    def _select_tables(self, user_text: str) -> str:
        tables = self._lookup(self._TABLES, user_text)
        if tables is None:
            tables = self._heuristic_tables(user_text)
        return json.dumps({"tables": tables, "reason": "（mock）规则匹配"},
                          ensure_ascii=False)

    def _generate_sql(self, user_text: str) -> str:
        sql = self._lookup(self._FIRST_ATTEMPT_BUGS, user_text)
        if sql is None:
            sql = self._lookup(self._SQL, user_text)
        if sql is None:
            # 未收录的问题：给一个保守的默认查询（演示用）
            sql = "SELECT COUNT(*) AS cnt FROM users"
        return f"思路略（mock）。\n```sql\n{sql}\n```"

    def _rewrite_sql(self, user_text: str) -> str:
        prev = re.search(r"```sql\s*\n(.*?)```", user_text, re.S)
        prev_sql = prev.group(1).strip() if prev else ""
        m = re.search(r"(?:列不存在|no such column)\s*[:：]?\s*([A-Za-z_][\w.]*)", user_text)
        if m and prev_sql:
            wrong = m.group(1)
            fixed = self._COLUMN_FIXES.get(wrong)
            if fixed:
                new_sql = prev_sql.replace(wrong, fixed)
                return f"```sql\n{new_sql}\n```"
        # 无法自动修复时原样返回，交由工作流走兜底逻辑
        return f"```sql\n{prev_sql}\n```"

    def _summarize(self, user_text: str) -> str:
        count = re.search(r"共\s*(\d+)\s*行", user_text)
        first_row = re.search(r"^\((.+)\)\s*$", user_text, re.M)
        n = count.group(1) if count else "若干"
        head = first_row.group(1).rstrip(",").strip() if first_row else ""
        return f"（mock）查询共返回 {n} 行结果。" + (f"首行数据：{head}。" if head else "")

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def _lookup(table: dict[str, object], user_text: str) -> object | None:
        norm_text = _normalize(user_text)
        for key, value in table.items():
            if _normalize(key) in norm_text:
                return value
        return None

    @staticmethod
    def _heuristic_tables(user_text: str) -> list[str]:
        text = user_text
        tables: list[str] = []
        if any(k in text for k in ("用户", "客户", "城市")):
            tables.append("users")
        if any(k in text for k in ("订单", "下单", "客单价", "平均")):
            tables.append("orders")
        if any(k in text for k in ("商品", "产品", "品类", "类目", "库存", "价格")):
            tables.append("products")
        if any(k in text for k in ("销量", "明细", "买了", "购买")):
            tables.append("order_items")
        if "order_items" in tables and "orders" not in tables:
            tables.append("orders")
        return tables or ["users", "orders", "products", "order_items"]


def _last_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def register_mock_knowledge(sql_by_question: dict[str, str],
                            tables_by_question: dict[str, list[str]],
                            first_attempt_bugs: dict[str, str] | None = None) -> None:
    """由评测模块把 15 条测试问题的 gold SQL 注册进 MockClient。"""
    MockClient._SQL = {k: v for k, v in sql_by_question.items()}
    MockClient._TABLES = {k: v for k, v in tables_by_question.items()}
    MockClient._FIRST_ATTEMPT_BUGS = dict(first_attempt_bugs or {})


def create_llm(cfg) -> BaseLLMClient:
    """按配置创建 LLM 客户端。"""
    if cfg.llm.provider == "mock":
        return MockClient(model="mock-offline")
    return DeepSeekClient(cfg.llm)


__all__ = ["BaseLLMClient", "DeepSeekClient", "MockClient", "LLMError",
           "LLMResponse", "create_llm", "register_mock_knowledge", "extract_sql"]
