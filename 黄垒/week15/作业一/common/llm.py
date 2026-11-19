"""LLM 调用封装：只依赖 openai SDK，走 OpenAI 兼容协议。

两个版本（langgraph / openai-agents）共用这一层，
区别只在于「谁来决定调用时机」：LangGraph 用图的节点和条件边，Agents SDK 用 Agent/Handoff。
"""

from __future__ import annotations

import json
import re

from openai import OpenAI

from . import config

_client: OpenAI | None = None


class LLMError(RuntimeError):
    """模型调用失败（网络 / 401 / 返回不是 JSON 等）。"""


def client() -> OpenAI:
    global _client
    if _client is None:
        if not config.has_llm():
            raise LLMError("未配置 LLM_API_KEY，请复制 .env.example 为 .env 后填入 Key")
        _client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            timeout=config.LLM_TIMEOUT,
            max_retries=1,
        )
    return _client


def chat(system: str, user: str, *, temperature: float = 0.6, max_tokens: int | None = None) -> str:
    """普通文本补全。"""
    try:
        resp = client().chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - 统一收敛成 LLMError
        raise LLMError(f"调用模型失败: {type(exc).__name__}: {exc}") from exc

    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise LLMError("模型返回空内容")
    return content


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def load_json(text: str) -> dict:
    """从模型输出里抠出 JSON：兼容 ```json 包裹、前后有解释、只有单个对象的情况。"""
    text = (text or "").strip()
    if not text:
        raise LLMError("模型返回空内容")

    candidates = [text]
    m = _JSON_BLOCK.search(text)
    if m:
        candidates.insert(0, m.group(1))

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise LLMError(f"模型返回的不是 JSON: {text[:120]}")


def chat_json(system: str, user: str, *, temperature: float = 0.0, max_tokens: int | None = None) -> dict:
    """要求模型输出 JSON；第一次解析失败会带着错误信息再要一次。"""
    messages = [
        {"role": "system", "content": system + "\n\n只输出一个 JSON 对象，不要 Markdown 代码块。"},
        {"role": "user", "content": user},
    ]
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = client().chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or config.LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            return load_json(resp.choices[0].message.content or "")
        except LLMError as exc:
            last_err = exc
            messages.append({"role": "user", "content": f"上一次输出不是合法 JSON（{exc}）。请只输出 JSON 对象。"})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"调用模型失败: {type(exc).__name__}: {exc}") from exc
    raise LLMError(f"两次都没拿到合法 JSON: {last_err}")
