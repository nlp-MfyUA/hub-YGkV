from dotenv import load_dotenv
from openai import OpenAI
import os

load_dotenv(dotenv_path="./.env.mimo", verbose=True)

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY未设置，请在.env中配置")

BASE_URL = os.getenv("BASE_URL")
if not BASE_URL:
    raise ValueError("BASE_URL未设置，请在.env中配置")

MODEL = os.getenv("MODEL")
if not MODEL:
    raise ValueError("MODEL未设置，请在.env中配置")

"""
作业二：
借助于llm tool call 或 json mode 能力，构建一个简单的情况情感分析智能体。提交实现代码。

输入：小明喜欢小姚，但是小姚喜欢小王。
输出：人物关系图谱

[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
]
"""

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

def relation_map(messages):
    # 1.发送请求
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"}
    )

    # 2.解析响应
    message = response.choices[0].message

    # 判断对方是否拒绝响应
    if message.refusal:
        print(f"模型拒绝了回答：{message.refusal}")
    else:
        if message.content:
            print(message.content)
        else:
            print(f"回答没有内容，查看结束原因:{response.choices[0].finish_reason}")


if __name__ == "__main__":

    # 1.创建消息体
    messages = [
        {"role": "system", "content": "你是一个专业的情感分析智能体"},
        {"role": "user", "content": """
            针对 小明喜欢小姚，但是小姚喜欢小王。 这段关系，输出一个人物关系图谱.请以 JSON 数组形式返回，每个对象包含 source, relation, target 三个字段。
            示例：
            [
                {
                    "source": "小明",
                    "relation": "爱慕",
                    "target": "小姚"
                }
            ]
            """}
    ]

    # 2.进行格式限制，但是deepseek不让使用json_schema，只能使用json_object
    """
    format = {
        "type": "json_schema",
        "json_schema": {
            "name": "relation_map",
            "strict": True,
            "schema": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": "string",
                        "relation": "string",
                        "target": "string"
                    },
                    "required": ["source", "relation", "target"],
                    "additionalProperties": False
                }
            }
        }
    }
    """

    # 3.输出关系图谱
    relation_map(messages)
