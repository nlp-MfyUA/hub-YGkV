"""OpenAI 兼容的大模型客户端。

通过统一适配 OpenAI 兼容的 /chat/completions 协议来支持多种大模型，
如 DeepSeek、Qwen(DashScope)、Zhipu GLM、SiliconFlow、OpenAI 等。
模型来源用环境变量配置（见 .env.example）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
_ENV_LOADED = False


def load_env(path: str | Path | None = None) -> None:
    """读取同目录 .env（浅解析，只支持 KEY=VALUE），不覆盖已有环境变量。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    p = Path(path) if path else (BASE_DIR / ".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    _ENV_LOADED = True


def get_config() -> dict:
    load_env()
    return {
        "base_url": (os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/"),
        "api_key": os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", ""),
        "model": os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }


def chat(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int = 180,
) -> str:
    cfg = get_config()
    if not cfg["api_key"]:
        raise RuntimeError("缺少 LLM API Key，请在 .env 中配置 LLM_API_KEY / DEEPSEEK_API_KEY")
    url = f"{cfg['base_url']}/chat/completions"
    payload = {"model": cfg["model"], "messages": messages, "temperature": temperature}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"LLM 返回异常: {data.get('error') or data}") from e


def extract_json(text: str) -> dict | list:
    """从模型输出中稳健抽取 JSON（容忍代码块围栏与前后杂文）。"""
    if not text:
        raise ValueError("空输出")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 兜底：抓取最外层花括号/方括号区块
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"无法解析 JSON: {text[:300]}")


def chat_json(
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int | None = None,
    retries: int = 2,
) -> dict | list:
    """请求模型输出 JSON 并解析；失败自动重试。

    解析失败的常见原因是模型输出被 max_tokens 截断成不完整 JSON，
    因此每次重试把 token 预算放大（默认 2 倍递增），提高一次成功的概率。
    """
    budget = max_tokens
    for attempt in range(retries + 1):
        try:
            content = chat(messages, temperature=temperature, max_tokens=budget)
        except Exception:
            raise
        try:
            return extract_json(content)
        except ValueError:
            if attempt == retries:
                raise ValueError(f"模型输出无法解析为 JSON，已重试 {retries} 次。原文: {content[:500]}")
            # 截断疑似元凶：给下次更大预算
            budget = None if budget is None else int(budget * 2)
    raise RuntimeError("unreachable")
