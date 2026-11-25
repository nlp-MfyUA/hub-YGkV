"""Model factory for OpenAI Agents SDK (real OpenAI-compatible model or deterministic MockAgentsModel)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from agents import (
    AgentOutputSchemaBase,
    Handoff,
    ModelResponse,
    ModelSettings,
    ModelTracing,
    OpenAIChatCompletionsModel,
    Tool,
    Usage,
)
from agents.items import TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model
from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from common.config import get_llm_settings
from common.mock_sentiment import analyze_sentiment_rule, generate_reply_rule


def _extract_user_text(input_data: str | list[TResponseInputItem]) -> str:
    if isinstance(input_data, str):
        return input_data
    parts: list[str] = []
    for item in input_data:
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
            if role == "user" and isinstance(content, str):
                parts.append(content)
            elif role == "user" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        parts.append(str(block["text"]))
    return "\n".join(parts)


def _message_response(text: str) -> ModelResponse:
    msg = ResponseOutputMessage(
        id="mock_msg_1",
        role="assistant",
        status="completed",
        type="message",
        content=[ResponseOutputText(text=text, type="output_text", annotations=[])],
    )
    return ModelResponse(output=[msg], usage=Usage(), response_id="mock_resp_1")


class MockAgentsModel(Model):
    """Deterministic Model implementation so OpenAI-Agents Runner + Handoffs run without an API key."""

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        user_text = _extract_user_text(input)
        sys_text = system_instructions or ""

        # 路由 Agent 只有一个由应用选好的移交目标。
        if handoffs:
            (chosen,) = handoffs
            call = ResponseFunctionToolCall(
                id="mock_call_1",
                call_id="mock_call_1",
                name=chosen.tool_name,
                arguments="{}",
                type="function_call",
                status="completed",
            )
            return ModelResponse(output=[call], usage=Usage(), response_id="mock_resp_handoff")

        # 2. Process 1: Sentiment recognition with structured output_schema
        if output_schema is not None:
            result = analyze_sentiment_rule(user_text)
            return _message_response(json.dumps(result.model_dump(), ensure_ascii=False))

        # 回应模板与实际接手的 Agent 指令一致。
        sentiment = "positive" if "鼓励" in sys_text else "negative"
        reply = generate_reply_rule(sentiment)
        return _message_response(reply)

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise NotImplementedError("Streaming is not required in MockAgentsModel")


def build_agents_model() -> Model:
    """Return OpenAIChatCompletionsModel when OPENAI_API_KEY is configured, else MockAgentsModel."""
    settings = get_llm_settings()
    if settings.mode == "openai":
        client = AsyncOpenAI(
            api_key=settings.api_key, base_url=settings.base_url, timeout=20.0, max_retries=0,
        )
        return OpenAIChatCompletionsModel(model=settings.model, openai_client=client)
    return MockAgentsModel()
