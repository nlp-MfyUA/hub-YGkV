import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from agents import Agent, ModelSettings, Runner, set_tracing_disabled
from agents.items import ModelResponse
from agents.models.interface import Model, ModelTracing
from agents.usage import Usage
from openai.types.responses import ResponseOutputMessage, ResponseOutputText



# =============================================================================

# 模型必须按这张表交卷。final_output 会变成这个类的对象。
class LanguageHit(BaseModel):
    language: str = Field(description="主体语种的中文名，例如：中文、英语、日语")
    is_chinese: bool = Field(description="主体是中文（简体或繁体都算）则为 true")


class Translation(BaseModel):
    text: str = Field(description="译文本身，不要解释")


# 三个角色的系统提示词。创建 Agent 时还不会请求模型。
DETECTOR_INSTRUCTIONS = """
你是语种判断器。只判断用户原文的主体语种。
language 用中文语种名。简体和繁体都算中文，is_chinese 为 true。
中外文夹杂时，汉字是语义主体则 is_chinese 为 true。
不要翻译，不要解释。
"""

TO_ENGLISH = """
你是翻译。把用户原文翻译成自然、准确的英文。
只给出译文。保留专名、数字和换行。不要解释。
"""

TO_CHINESE = """
你是翻译。把用户原文翻译成自然、准确的简体中文。
只给出译文。保留专名、数字和换行。不要解释。
"""


def build_agents(model):
    """造出三个 Agent。model 可以是模型名，也可以是下面的 WorkBuddy 模型对象。"""
    common = {}
    if isinstance(model, str):
        # gpt-5 不接受 temperature，其他模型用 0，输出更稳定。
        settings = ModelSettings() if model.startswith("gpt-5") else ModelSettings(temperature=0)
        common = {"model": model, "model_settings": settings}
    elif model is not None:
        common = {"model": model}

    detector = Agent(
        name="language_detector",
        instructions=DETECTOR_INSTRUCTIONS,
        output_type=LanguageHit,  # 跑完后 final_output 是 LanguageHit
        **common,
    )
    to_english = Agent(
        name="to_english",
        instructions=TO_ENGLISH,
        output_type=Translation,
        **common,
    )
    to_chinese = Agent(
        name="to_chinese",
        instructions=TO_CHINESE,
        output_type=Translation,
        **common,
    )
    return detector, to_english, to_chinese


def translate(text: str, model) -> dict:
    """中文译成英文，其他语种译成中文。返回的字典就是要打印的 JSON。"""
    detector, to_english, to_chinese = build_agents(model)

    # 第一次请求：只判断语种。run_sync 会停在这里，直到模型回答。
    detected = Runner.run_sync(detector, text)
    hit = detected.final_output
    if not isinstance(hit, LanguageHit):
        raise TypeError(type(hit).__name__)

    # 岔路由 Python 走。模型只填表，不负责选下一个角色。
    translator = to_english if hit.is_chinese else to_chinese

    # 第二次请求：只翻译。送进去的仍是用户原文。
    translated = Runner.run_sync(translator, text)
    body = translated.final_output
    if not isinstance(body, Translation):
        raise TypeError(type(body).__name__)

    return {
        "query_input": text,  # 用用户原文，不用模型回显
        "language": hit.language.strip() or ("中文" if hit.is_chinese else "未知"),
        "result": body.text.strip(),
    }



# =============================================================================

_ENDPOINT = "https://llm-bridge-32625.app.workbuddy.host"
_KEY_HEADER = "x-wb-webapp-access-key"
_README = Path("/mnt/d/wb/2026-10-09-13-37-54/langchain_workbuddy/README.md")


def find_workbuddy_key() -> str:
    saved = os.environ.get("WB_PUBLISHABLE_KEY")
    if saved is not None:
        return saved.strip()
    if not _README.is_file():
        return ""
    matched = re.search(r"WB_PUBLISHABLE_KEY=(wbpk_[A-Za-z0-9_]+)", _README.read_text(encoding="utf-8"))
    return matched.group(1) if matched else ""


def _as_text(model_input) -> str:
    """SDK 有时传来的是消息列表，取出里面的用户原文。"""
    if isinstance(model_input, str):
        return model_input
    if not isinstance(model_input, list):
        return str(model_input)
    parts: list[str] = []
    for item in model_input:
        if isinstance(item, str):
            parts.append(item)
            continue
        payload = item if isinstance(item, dict) else {}
        if not payload and hasattr(item, "model_dump"):
            payload = item.model_dump()
        content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
                elif isinstance(part, str):
                    parts.append(part)
    return "\n".join(parts) if parts else str(model_input)


class WorkBuddyCloudModel(Model):
    """把 WorkBuddy 的流式接口收成 Agents SDK 能用的一次回答。"""

    def __init__(self, model_name: str, api_key: str) -> None:
        self.model_name = model_name
        self.api_key = api_key

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id,
        conversation_id,
        prompt,
    ) -> ModelResponse:
        del model_settings, tools, handoffs, tracing, previous_response_id, conversation_id, prompt
        instructions = system_instructions or ""
        if output_schema is not None and not output_schema.is_plain_text():
            schema = json.dumps(output_schema.json_schema(), ensure_ascii=False)
            instructions += "\n\n只输出一个 JSON 对象，不要代码块。符合这个 JSON Schema：\n" + schema
        messages = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        messages.append({"role": "user", "content": _as_text(input)})
        text = self._complete(messages).strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        message = ResponseOutputMessage(
            id="wb",
            role="assistant",
            type="message",
            status="completed",
            content=[ResponseOutputText(text=text, type="output_text", annotations=[], logprobs=[])],
        )
        return ModelResponse(output=[message], usage=Usage(requests=1), response_id=None)

    def stream_response(self, *args, **kwargs) -> AsyncIterator[Any]:
        del args, kwargs

        async def _unused() -> AsyncIterator[Any]:
            raise NotImplementedError
            yield None

        return _unused()

    def _complete(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({"model": self.model_name, "messages": messages, "stream": True}).encode()
        request = urllib.request.Request(
            f"{_ENDPOINT}/.cloud/llm/chat/completions",
            data=payload,
            headers={
                _KEY_HEADER: self.api_key,
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        pieces: list[str] = []
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("content"):
                        pieces.append(delta["content"])
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode("utf-8", "replace")[:300]) from None
        text = "".join(pieces).strip()
        if not text:
            raise RuntimeError("WorkBuddy 没有返回正文")
        return text


def choose_model():
    """有 OpenAI 密钥就用官方模型，否则用 WorkBuddy 的 space-bunny。"""
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return os.environ.get("OPENAI_MODEL", "gpt-5-nano")
    key = find_workbuddy_key()
    if not key:
        raise SystemExit("没有 OPENAI_API_KEY，也没有找到 WorkBuddy 密钥。")
    set_tracing_disabled(True)
    return WorkBuddyCloudModel(os.environ.get("WB_MODEL", "space-bunny"), key)


def main() -> None:
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("请输入文本：")
    # 空文本、纯数字不调用模型，仍然打印同样的三个字段。
    if not text.strip() or not any(ch.isalpha() for ch in text):
        reason = "输入为空" if not text.strip() else "无法判断语种：输入没有可识别的文字"
        result = {"query_input": text, "language": "未知", "result": reason}
    else:
        result = translate(text, choose_model())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
