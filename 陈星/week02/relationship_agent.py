"""作业2：基于 LLM tool call 的人物关系抽取智能体。

输入一段文本，输出「人物关系图谱」——即三元组（source / relation / target）列表。
做法：给模型定义一个 record_relationships 工具，让模型以"调用工具"的方式
把识别到的人物关系结构化地吐出来，而不是自由文本。
"""
import json
from typing import Dict, List

from llm_client import get_client, get_config

# 工具定义：模型通过调用该工具来输出结构化关系
RELATION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_relationships",
        "description": "提取文本中出现的人物关系，并以三元组列表形式记录。",
        "parameters": {
            "type": "object",
            "properties": {
                "triples": {
                    "type": "array",
                    "description": "人物关系三元组列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "关系的主体（人物）"},
                            "relation": {
                                "type": "string",
                                "description": "两者之间的关系，如 爱慕/喜欢/厌恶/朋友",
                            },
                            "target": {"type": "string", "description": "关系的客体（人物）"},
                        },
                        "required": ["source", "relation", "target"],
                    },
                }
            },
            "required": ["triples"],
        },
    },
}


def extract_relationships(text: str) -> List[Dict[str, str]]:
    """调用 LLM（tool call）从文本中抽取人物关系图谱。"""
    cfg = get_config()
    client = get_client()

    system = (
        "你是一个人物关系抽取智能体。请仔细阅读用户输入的文本，"
        "识别其中所有人物之间的关系，并用 record_relationships 工具输出。"
        "关系词要符合中文语义（如：爱慕、喜欢、厌恶、朋友、兄妹等），"
        "关系词请做归一化（例如：'喜欢'规范为'爱慕'，'讨厌/烦'规范为'厌恶'），"
        "不要编造文本中不存在的关系；一个人出现在多段关系中要分别记录。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]

    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=messages,
        tools=[RELATION_TOOL],
        tool_choice="auto",
    )
    msg = resp.choices[0].message

    triples: List[Dict[str, str]] = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            if tc.function.name == "record_relationships":
                data = json.loads(tc.function.arguments)
                for t in data.get("triples", []):
                    if t.get("source") and t.get("relation") and t.get("target"):
                        triples.append(
                            {
                                "source": t["source"],
                                "relation": t["relation"],
                                "target": t["target"],
                            }
                        )
    return triples


if __name__ == "__main__":
    text = "小明喜欢小姚，但是小姚喜欢小王。"
    graph = extract_relationships(text)
    print(json.dumps(graph, ensure_ascii=False, indent=2))
