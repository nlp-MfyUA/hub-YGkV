import json
import math
from openai import OpenAI


client = OpenAI(
    api_key="sk-djdzrwnmzqtcbbagdrmcychkfwyuiwahoetdoketuzpvdjkt",
    base_url="https://api.siliconflow.cn/v1",
)


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


system_content="""
从用户的文字描述中提取人物之间的信息，以 JSON 格式输出，包含以下字段：
- source: 描述开头内容，例如张三喜欢李四，返回张三
- relation: 行为，例如喜欢、爱慕
- target: 比如喜欢谁，例如张三喜欢李四，返回李四


JSON 输出示例：
{
    "source": "张三",
    "relation": 喜欢,
    "target": 李四
}
"""

messages = [
    {"role": "system", "content": system_content},
    {"role": "user", "content": "帮我整理以下内容，小明喜欢小桃，但是小桃喜欢小王"
    }
]





response=client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V4-Flash",
    messages=messages,
    response_format={"type": "json_object"},
    # tools=TOOLS,
    temperature=0.0,
    max_tokens=512,      # 最大输出长度
    n=1,                 # 只生成一个回答（默认值就是1，但显式写出来更明确）
    stop=None            # 不设停止词，让模型自然结束

)

content = response.choices[0].message.content
print(f"模型返回内容：{content}")
result = safe_json_parse(content)
print(f"json解析后的内容：{result}")

