#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vLLM（OpenAI 兼容）客户端：只要流式。

一个细节：Qwen3.5 默认可能输出 ` think...<｜end▁of▁thinking｜>` 思考段，这里统一在流里过滤掉，
前端拿到的就是干净的答案；同时把 thinking 单独作为事件透传，UI 可以折叠显示。
"""

import json
import logging
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx

import config

log = logging.getLogger("llm")

_THINK_OPEN = re.compile(r"^\s*<think[^>]*>", re.I)
_THINK_CLOSE = re.compile(r"</think[^>]*>\s*", re.I)


class _ThinkFilter:
    """跨 token 边界判断 thinking 段：进 <think 之后的内容丢进 think 回调。"""

    def __init__(self) -> None:
        self.in_think = False
        self.buf = ""

    def feed(self, text: str) -> Tuple[str, str]:
        """返回 (answer_text, think_text)。"""
        self.buf += text
        answer, think = [], []
        while self.buf:
            if not self.in_think:
                idx = self.buf.find("<think")
                if idx < 0:
                    # 可能刚好切在 "<thi" 这种前缀上，留 8 个字符观察
                    if len(self.buf) > 8 and not self.buf.endswith("<"):
                        answer.append(self.buf[:-8])
                        self.buf = self.buf[-8:]
                    break
                if idx > 0:
                    answer.append(self.buf[:idx])
                self.buf = self.buf[idx:]
                end = self.buf.find(">")
                if end < 0:
                    break
                self.buf = self.buf[end + 1:]
                self.in_think = True
            else:
                idx = self.buf.find("</think")
                if idx < 0:
                    if len(self.buf) > 10:
                        think.append(self.buf[:-10])
                        self.buf = self.buf[-10:]
                    break
                think.append(self.buf[:idx])
                self.buf = self.buf[idx:]
                end = self.buf.find(">")
                if end < 0:
                    break
                self.buf = self.buf[end + 1:]
                self.in_think = False
        return "".join(answer), "".join(think)

    def flush(self) -> Tuple[str, str]:
        rest, self.buf = self.buf, ""
        return ("", rest) if self.in_think else (rest, "")


def stream_chat(messages: List[Dict[str, Any]],
                temperature: Optional[float] = None,
                max_tokens: Optional[int] = None) -> Iterator[Dict[str, Any]]:
    """产出 {"type": "delta"|"think"|"usage", ...}。"""
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": config.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    tf = _ThinkFilter()
    with httpx.Client(base_url=config.LLM_BASE_URL, timeout=config.LLM_TIMEOUT,
                      trust_env=False) as client:
        with client.stream("POST", "/chat/completions", json=payload,
                           headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}) as r:
            if r.status_code >= 300:
                body = "".join(r.iter_text())[:600]
                raise RuntimeError(f"vLLM 返回 {r.status_code}: {body}")
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    yield {"type": "usage", "usage": obj["usage"]}
                for ch in obj.get("choices") or []:
                    piece = (ch.get("delta") or {}).get("content") or ""
                    if not piece:
                        continue
                    ans, think = tf.feed(piece)
                    if think:
                        yield {"type": "think", "text": think}
                    if ans:
                        yield {"type": "delta", "text": ans}
    ans, think = tf.flush()
    if think:
        yield {"type": "think", "text": think}
    if ans:
        yield {"type": "delta", "text": ans}


def health() -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=5.0, trust_env=False) as c:
            r = c.get(f"{config.LLM_BASE_URL}/models",
                      headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        ids = [m.get("id") for m in (r.json().get("data") or [])]
        return {"ok": True, "models": ids, "using": config.LLM_MODEL}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
