#构建一个简单的情感分析智能体
#通过jsonModels来实现情感分析功能

import json
import re
from openai import OpenAI

def safe_json_parse(text: str) -> dict | list | None:
    """安全解析 JSON，处理可能的空 content、<think> 块和格式异常。"""
    if not text or not text.strip():
        print("    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    # 先剥离推理模型的 <think>... 块
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # 顺手去掉 markdown 代码块标记 ```json ... ```
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    decoder = json.JSONDecoder()
    try:
        # raw_decode 能容忍 JSON 之后的额外文本，只解析到第一个合法 JSON 结束
        obj, _ = decoder.raw_decode(text)
        return obj
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        print(f"    原始内容: {text[:200]}")
        return None



client = OpenAI(
    api_key="sk-cp-mEeFZRSWbWzFdg5og740Eac0Lu1fZGO2yo_O2EBqleWlXqT7JOM51DnnL76FaTz9wgKgwiwb74QAj8ujsXgsJ2QHvkrbVAjRb4QVCpYSJzDLDTSS2rF0dWw",
    base_url="https://api.minimaxi.com/v1",
)


print("=" * 65)
print("一个简单的情感分析智能体")
print("=" * 65)

prompt = (
    "分析以下句子的情感倾向（爱慕 / 不喜欢 / 中立）。\n"
    "句子：小明喜欢小姚，但是小姚喜欢小王"
)

system_json = """
你是一个情感分析助手。请严格按以下要求输出：
1. 只输出一个 JSON 数组，不要任何前后缀、解释、说明或 markdown 代码块标记。
2. 数组中每个对象描述句子中的一条人物关系。
3. 字段：source（主角）、relation（爱慕 / 不喜欢 / 中立）、target（目标人物）。

JSON 示例（不要包含 ``` 标记，直接输出 JSON 本身并严格按照下面格式输出）：
[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
]
"""

resp_json = client.chat.completions.create(
    model="MiniMax-M3",
    messages=[
        {"role": "system", "content": system_json},
        {"role": "user", "content": prompt},
    ],
    response_format={"type": "json_object"},
    max_tokens=2000,
    temperature=0.0,
)

content = resp_json.choices[0].message.content
result = safe_json_parse(content) if content is not None else None

print(f" {prompt}")

if result is not None:
    print(f"\n     情感分析结果:\n{json.dumps(result, ensure_ascii=False, indent=4)}")
    
print()