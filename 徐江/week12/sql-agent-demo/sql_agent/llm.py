"""LLM 层（LangChain ChatModel 抽象）。

week11 版在这里裸调 OpenAI SDK（自建 DeepSeekClient + MockClient）；
week12 版改为 LangChain 的标准抽象——所有模型都是 ``BaseChatModel``：

- :func:`create_chat_model` 按配置返回对应的 ChatModel 实例：
  - ``deepseek`` → ``langchain_openai.ChatOpenAI``（OpenAI 兼容协议，
    底层的 openai SDK、网络重试、token 统计全部由 LangChain 托管）；
  - ``mock`` → :class:`MockChatModel`（自定义 ``BaseChatModel``，离线模拟）；
- :class:`MockChatModel` 与真实模型实现同一接口，因此四条 LCEL 链
  （见 ``chains.py``）对两种模型完全一致——切换模型零成本，这正是
  LangChain 模型抽象的价值。

公共接口（LangChain 惯例）：

    model.invoke([SystemMessage(...), HumanMessage(...)]) -> AIMessage
    # AIMessage.content           模型文本输出
    # AIMessage.usage_metadata    {"input_tokens"/"output_tokens"/"total_tokens"}
    # AIMessage.response_metadata {"model_name": ...}
"""
from __future__ import annotations

import json
import re
from typing import ClassVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .config import LLMConfig
from .prompts import TASK_KEYWORDS, extract_sql

__all__ = ["LLMError", "BaseChatModel", "MockChatModel", "DeepSeekChat",
           "create_chat_model", "create_llm", "register_mock_knowledge",
           "chat_model_name", "extract_sql"]


class LLMError(RuntimeError):
    """LLM 不可用（未配置 Key / 鉴权失败 / 网络错误等）。

    与 week11 语义一致：stage 捕获到该错误会标记 llm_failed=True，
    工作流随即短路（继续改写只是浪费调用）。
    """


def chat_model_name(model: BaseChatModel) -> str:
    """取模型名（ChatOpenAI 用 model_name 字段，兼容其他实现的 model 字段）。"""
    return str(getattr(model, "model_name", None) or getattr(model, "model", "") or "")


# ====================================================================== 真实 API
def create_deepseek_model(cfg: LLMConfig) -> BaseChatModel:
    """创建 DeepSeek（OpenAI 兼容）ChatModel —— langchain_openai.ChatOpenAI。

    网络层重试由底层 openai SDK 负责（max_retries=cfg.net_max_retries，
    仅限流 / 超时 / 5xx 才重试，鉴权失败立即报错）。
    """
    if not cfg.api_key:
        raise LLMError(
            "未配置 API Key。请编辑 config.local.yaml，在 llm.api_key 处填入 "
            "DeepSeek Key（或设置环境变量 LLM_API_KEY）。"
        )
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover
        raise LLMError(
            "缺少依赖 langchain-openai，请先执行: pip install -r requirements.txt"
        ) from exc
    try:
        return ChatOpenAI(
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout_seconds,
            max_retries=cfg.net_max_retries,
        )
    except Exception as exc:  # noqa: BLE001 - SSL_CERT_FILE 无效等构造期错误
        raise LLMError(f"LLM 客户端创建失败: {type(exc).__name__}: {exc}") from exc


# 别名：语义同 create_deepseek_model（DeepSeek 走 OpenAI 兼容协议）
DeepSeekChat = create_deepseek_model


# ====================================================================== 离线模拟
def _normalize(text: str) -> str:
    return re.sub(r"[\s，。？！、,.?!]+", "", text)


def _last_user_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if msg.type == "human":
            return str(msg.content)
    return ""


def _system_text(messages: list[BaseMessage]) -> str:
    for msg in messages:
        if msg.type == "system":
            return str(msg.content)
    return ""


class MockChatModel(BaseChatModel):
    """离线模拟 ChatModel：按 system prompt 特征分派任务，用固定规则模拟 LLM 输出。

    用途：
    1. 没有 API Key 时也能把「数据库解析 → 选表 → 生成 → 校验 → 改写 → 执行 → 汇总」
       整条链路跑通，验证代码与报告；
    2. 内置一个「首次故意写错列名」的用例（Q8），用来演示 校验失败 → 改写 → 重试 回路。

    因为它实现了 LangChain 的 ``BaseChatModel`` 接口，四条 LCEL 链对它和
    对真实 ChatOpenAI 完全一致（``prompt | model | parser``），只是把模型
    换成它即可离线运行。切换到真实模型只需在配置里填入 Key 并将 provider
    改为 deepseek。

    任务分派依据 system prompt 特征词（与 dev/mock_openai_server.py 同一思路），
    特征词集中在 prompts.TASK_KEYWORDS，改 prompt 时同步即可。
    """

    model_name: str = "mock-offline"

    # ---- MockClient 知识库（ClassVar：非 pydantic 字段，可整体替换）----
    # 问题（归一化后）-> 选中的表
    TABLES: ClassVar[dict[str, list[str]]] = {}
    # 问题（归一化后）-> 正确 SQL
    SQL: ClassVar[dict[str, str]] = {}
    # 问题（归一化后）-> 首次生成时故意埋下的错误 SQL（用于演示改写回路）
    FIRST_ATTEMPT_BUGS: ClassVar[dict[str, str]] = {}

    # 常见列名错误 -> 正确列名（改写阶段依据报错信息修复）
    COLUMN_FIXES: ClassVar[dict[str, str]] = {
        "orders.amount": "orders.total_amount",
        "orders.total": "orders.total_amount",
        "users.name": "users.user_name",
        "products.name": "products.product_name",
        "orders.date": "orders.order_date",
        "order.date": "orders.order_date",
    }

    @property
    def _llm_type(self) -> str:
        return "mock-chat"

    # ---------------------------------------------------------------- LangChain 接口
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        system = _system_text(messages)
        user_text = _last_user_text(messages)
        content = self._dispatch(system, user_text)
        message = AIMessage(
            content=content,
            response_metadata={"model_name": self.model_name},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    # ------------------------------------------------------------ 各任务模拟
    def _dispatch(self, system: str, user_text: str) -> str:
        # 顺序即优先级：select -> rewrite -> generate -> summarize
        if TASK_KEYWORDS["select_tables"] in system:
            return self._select_tables(user_text)
        if TASK_KEYWORDS["rewrite_sql"] in system:
            return self._rewrite_sql(user_text)
        if TASK_KEYWORDS["generate_sql"] in system:
            return self._generate_sql(user_text)
        if TASK_KEYWORDS["summarize"] in system:
            return self._summarize(user_text)
        return "（mock 客户端）未识别的任务类型。"

    def _select_tables(self, user_text: str) -> str:
        tables = self._lookup(self.TABLES, user_text)
        if tables is None:
            tables = self._heuristic_tables(user_text)
        return json.dumps({"tables": tables, "reason": "（mock）规则匹配"},
                          ensure_ascii=False)

    def _generate_sql(self, user_text: str) -> str:
        sql = self._lookup(self.FIRST_ATTEMPT_BUGS, user_text)
        if sql is None:
            sql = self._lookup(self.SQL, user_text)
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
            fixed = self.COLUMN_FIXES.get(wrong)
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


def register_mock_knowledge(sql_by_question: dict[str, str],
                            tables_by_question: dict[str, list[str]],
                            first_attempt_bugs: dict[str, str] | None = None) -> None:
    """由评测模块把 15 条测试问题的 gold SQL 注册进 MockChatModel。"""
    MockChatModel.SQL = {k: v for k, v in sql_by_question.items()}
    MockChatModel.TABLES = {k: v for k, v in tables_by_question.items()}
    MockChatModel.FIRST_ATTEMPT_BUGS = dict(first_attempt_bugs or {})


# ====================================================================== 工厂
def create_chat_model(cfg) -> BaseChatModel:
    """按配置创建 LangChain ChatModel（provider: deepseek | mock）。"""
    if cfg.llm.provider == "mock":
        return MockChatModel()
    return create_deepseek_model(cfg.llm)


# 向后兼容的别名（week11 调用方使用 create_llm）
create_llm = create_chat_model
