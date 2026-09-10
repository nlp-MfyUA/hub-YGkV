"""OpenAI 兼容 LLM 调用 + 强制 JSON 输出。

健康检测约定（不做自动轮询）：
1. 添加模型时手动"测试连接"（ping，max_tokens=1，10s 超时）
2. 列表页徽标 + 手动重检按钮
3. 研究任务运行前对所用模型探活一次，失败直接 error 终止
"""
import json
import re
from datetime import datetime

from openai import OpenAI

import db

JSON_INSTRUCTION = (
    "你必须只输出一个合法的 JSON 对象，不要输出 markdown 代码块、解释或其他任何内容。"
)


def _client(model: dict) -> OpenAI:
    from keyciphers import decrypt
    # 默认 180s：综合报告一次生成几千字 Markdown，60s 会超时
    return OpenAI(base_url=model["base_url"].rstrip("/"), api_key=decrypt(model["api_key_enc"]), timeout=180)


def _extract_json(text: str) -> dict:
    """从模型输出中提取 JSON 对象：优先整体解析，失败则取首个 { ... } 块。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def chat_json(model: dict, system: str, user: str, temperature: float = 0.3, max_tokens: int = 2048) -> dict:
    """LLM 调用并强制 JSON；解析失败追加指令重试一次。"""
    client = _client(model)
    for attempt in range(2):
        prompt = user if attempt == 0 else user + "\n\n" + JSON_INSTRUCTION
        resp = client.chat.completions.create(
            model=model["model_name"],
            messages=[
                {"role": "system", "content": system + "\n" + JSON_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            return _extract_json(resp.choices[0].message.content or "")
        except (json.JSONDecodeError, RuntimeError) as e:
            if attempt == 1:
                raise RuntimeError(f"模型 JSON 输出解析失败: {e}") from e


def chat_text(model: dict, system: str, user: str, temperature: float = 0.4, max_tokens: int = 4096) -> str:
    client = _client(model)
    resp = client.chat.completions.create(
        model=model["model_name"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def health_check(model: dict, model_id: int) -> bool:
    """探活：ping 请求（max_tokens=1），10s 超时。写回 health_status。"""
    ok = False
    try:
        client = _client(model)
        client.chat.completions.create(
            model=model["model_name"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=10,
        )
        ok = True
    except Exception:
        ok = False
    db.execute(
        "UPDATE models SET health_status = ?, health_at = ? WHERE id = ? AND user_id = ?",
        ("ok" if ok else "fail", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), model_id, model["user_id"]),
    )
    return ok
