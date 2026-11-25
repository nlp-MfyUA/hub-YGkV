"""LLM factory for LangGraph nodes (real ChatOpenAI or deterministic local MockChatModel)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from common.config import get_llm_settings
from common.mock_sentiment import analyze_sentiment_rule, generate_reply_rule


class MockChatModel(BaseChatModel):
    """Deterministic BaseChatModel so LangGraph runs end-to-end without an API key."""

    @property
    def _llm_type(self) -> str:
        return "mock-sentiment-chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system_text = "\n".join(str(m.content) for m in messages if m.type == "system")
        user_text = "\n".join(str(m.content) for m in messages if m.type == "human")

        if "情感识别" in system_text:
            result = analyze_sentiment_rule(user_text)
            payload = result.model_dump()
            content = json.dumps(payload, ensure_ascii=False)
        else:
            sentiment = "positive" if "鼓励" in system_text else "negative"
            content = generate_reply_rule(sentiment)

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def build_chat_model() -> BaseChatModel:
    """Return ChatOpenAI when OPENAI_API_KEY is configured, else MockChatModel."""
    settings = get_llm_settings()
    if settings.mode == "openai":
        return ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=20.0,
            max_retries=0,
        )
    return MockChatModel()
