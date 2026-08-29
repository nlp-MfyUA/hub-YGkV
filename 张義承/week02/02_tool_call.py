import os
from openai import OpenAI
import json

# 从本地环境变量读取 api_key
api_key = os.getenv("API_KEY")
if not api_key:
    raise ValueError("环境变量 API_KEY 未设置，请先设置再运行程序")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.minimaxi.com/v1",
)


def send_messages(messages):
    response = client.chat.completions.create(
        model="MiniMax-M2.7-highspeed",
        messages=messages,
        tools=tools,
        tool_choice="required",
        extra_body={
            "thinking": {"type": "disabled"},
        },
    )
    print("=" * 70)
    print("\n*******invoke func send_messages:*******")
    print(f"\nmodel_output->: \n{response}")
    return response.choices[0].message


def analyze_mod(elements: list, relations: list) -> json:
    data = []
    index = 0

    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):  # j 从 i+1 开始，避免重复和自身组合
            relation = relations[index % len(relations)]
            data.append(
                {"source": elements[i], "target": elements[j], "relation": relation}
            )
            index += 1

    return f"\n人物关系图谱为: \n{json.dumps(data, ensure_ascii=False, indent=2)}"


tools = [
    {
        "type": "function",
        "function": {
            "name": "analyze_mod",
            "description": "Get relation between more than two people or things",
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "list",
                        "description": "people or things",
                    },
                    "relations": {
                        "type": "list",
                        "description": "Relation between entities, only one word. e.g. like, dislike, hate, love, dependence",
                    },
                },
            },
            "required": ["elements", "relations"],
        },
    },
]

messages = [
    {
        "role": "user",
        "content": "小明喜欢小姚，但是小姚喜欢小王。（使用tool_calls）",
    }
]

FUNC_NAMES = {"analyze_mod": analyze_mod}

print("=" * 70)
print("*******User Input:*******")
print(f"\nUser>\t {messages[0]['content']}")

print("=" * 70)
print("\n*******LLM Output:*******")
message = send_messages(messages)
print(f"\nsend_messages return: \n{message}")

print("=" * 70)
print("\n*******Tool Calls Information:*******")
tool = message.tool_calls[0]
print(f"Tool Id: {tool.id}")
print(f"Tool Name: {tool.function.name}")
print(f"Tool Arguments: {tool.function.arguments}")

func_args = json.loads(tool.function.arguments)
fun_name = tool.function.name
tool_result = FUNC_NAMES[fun_name](**func_args)

messages.append(message)
messages.append({"role": "tool", "tool_call_id": tool.id, "content": tool_result})
messages.append({"role": "user", "content": "请用 JSON 格式输出分析结果"})

print("*******第2次 messages:*******")
for message in messages:
    print(f"\n第2次 User>\n {message}")

message = send_messages(messages)
print(f"\n最终回复: {message.content}")
