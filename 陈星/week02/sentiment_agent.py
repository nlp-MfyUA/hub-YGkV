"""作业2：基于 LLM tool call 的情感分析智能体。

输入一段文本（或批量），输出情感标签（正面 / 负面 / 中性）、
置信度与简要理由。做法：定义一个 analyze_sentiment 工具，
让模型以"调用工具"的方式把情感结构化地吐出来，而不是自由文本。
"""
import json
from typing import Dict, List, Optional

from llm_client import get_client, get_config

# 工具定义：模型通过调用该工具来输出结构化情感结果
SENTIMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "record_sentiment",
        "description": "对输入文本进行情感分析，输出情感极性、置信度与判断理由。",
        "parameters": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "enum": ["正面", "负面", "中性"],
                    "description": "情感极性",
                },
                "confidence": {
                    "type": "number",
                    "description": "置信度，0~1 之间的小数",
                },
                "reason": {
                    "type": "string",
                    "description": "判断依据，一句话简要说明",
                },
            },
            "required": ["label", "confidence", "reason"],
        },
    },
}


def analyze_sentiment(text: str) -> Dict[str, object]:
    """调用 LLM（tool call）分析单条文本情感。"""
    cfg = get_config()
    client = get_client()

    system = (
        "你是一个情感分析智能体。请仔细阅读用户输入的文本，"
        "判断其情感极性（正面 / 负面 / 中性），给出 0~1 的置信度，"
        "并用一句话说明判断理由。只依据文本本身，不要过度解读或编造。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]

    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=messages,
        tools=[SENTIMENT_TOOL],
        tool_choice="auto",
    )
    msg = resp.choices[0].message

    result: Dict[str, object] = {"label": "中性", "confidence": 0.0, "reason": ""}
    if msg.tool_calls:
        for tc in msg.tool_calls:
            if tc.function.name == "record_sentiment":
                data = json.loads(tc.function.arguments)
                result = {
                    "label": data.get("label", "中性"),
                    "confidence": float(data.get("confidence", 0.0)),
                    "reason": data.get("reason", ""),
                }
    return result


def analyze_batch(texts: List[str]) -> List[Dict[str, object]]:
    """批量情感分析。"""
    return [analyze_sentiment(t) for t in texts]


if __name__ == "__main__":
    samples = [
        "这家店的服务态度真好，下次还来！",
        "快递太慢了，等了一周还没到，很失望。",
        "今天天气多云，没什么特别的。",
    ]
    for t in samples:
        print(t, "->", analyze_sentiment(t))
