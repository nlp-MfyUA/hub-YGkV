import json
from openai import OpenAI
from llm_client import LLMClient


def safe_json_parse(text: str) -> dict | list | None:
    """安全解析 JSON，处理可能的空 content 和格式异常。"""
    if not text or not text.strip():
        print("    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        # 尝试修复常见问题：删除 markdown 代码块标记
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    原始内容: {text[:200]}")
            return None


def analysis_agent(user_prompt: str) -> dict | None:
    system_prompt = """
用户会提供一些情感问题或者关于自身情感的内容。请从中分析问题或内容的情感脉络，并将情感脉络中的关系以 JSON 格式输出。

输入示例：
小明喜欢小姚，但是小姚喜欢小王。

JSON 输出示例：
[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    },
    {
        "source": "小姚",
        "relation": "爱慕",
        "target": "小王"
    }
]
"""
    llm_client = LLMClient()
    messages = [{"role": "system", "content": system_prompt}]
    list_dict:list[dict] = llm_client._make_messages(user_prompt)

    if list_dict and len(list_dict) > 0:
        messages.append(list_dict[0])

    content = llm_client.chat_v2(messages=messages)
    result = safe_json_parse(content)

    return result

if __name__ == "__main__":
    user_prompt = "小李对小张有好感，小张不喜欢小李，但是暗恋小陈"
    result = analysis_agent(user_prompt=user_prompt)

    if result and len(result) > 0:
        print(f"  解析结果:")
        for item in result:
            print(f"    source:  {item['source']}")
            print(f"    relation: {item['relation']}")
            print(f"    target:   {item['target']}")
