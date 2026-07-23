from openai import OpenAI
import json

# 去掉base_url末尾多余逗号
client = OpenAI(
    api_key="sk-halxmsnmydbzgughfdiqypyzjjcedjjbsyuubmqatarghooc",
    base_url="https://api.siliconflow.cn"
)

# 工具定义无修改，结构正常
tools = [
    {
        "type": "function",   # 固定死，代表调用自定义函数，永远写function
        "function": {
            "name": "love_relation",   # 自定义：你要调用的工具函数名字
            "description": "抽取全部人物爱慕喜欢关系，所有关系必须放进relations数组，不能漏掉任何一组",   # 描述函数的作用功能
            "parameters": {
                "type": "object",   # 固定：参数整体是对象
                "required": ["relations"],    # 必填参数清单，模型必须返回这些key
                "properties": {    # 详细定义每一个参数的格式、类型、含义
                    "relations": {
                        "type": "array", # 固定参数："数组/字符串/数字" 
                        "items": {
                            "type": "object",
                            "properties": {  # 针对这个items对应的参数
                                "source": {"type": "string", "description": "主动爱慕的人"},
                                "relation": {"type": "string", "description": "固定值：爱慕"},
                                "target": {"type": "string", "description": "被爱慕的人"}
                            },
                            "required": ["source", "relation", "target"]
                        }
                    }
                }
            }
        }
    }
]

def love_relation(relations):
    return relations


def run_agent_with_toolcall(input_text: str):
    messages = [
        {
            "role": "system",
            "content": "你是情感分析智能体，文本中出现人物互相喜欢、爱慕的关系，必须调用love_relation工具输出关系图谱。无情感关系传入空数组。"
        },
        {"role": "user", "content": input_text}
    ]

    response = client.chat.completions.create(
        model="Pro/MiniMaxAI/MiniMax-M2.5",
        messages=messages,  # 把messages显式放进来，杜绝漏识别
        tools=tools,
        temperature=0
    )

    # 获取模型返回的message，一般默认取第一条内容的回复，这个写法可以当作是固定写法（除非是要获取模型生成的多条回复内容，才用其他的方式）
    msg = response.choices[0].message 


    # 判断模型是否调用了工具函数，如果meissage有tool_calls属性，则说明模型调用了工具函数，如果没有则返回空数组
    if msg.tool_calls:
        tool_call = msg.tool_calls[0]  # 获取工具函数的参数，当前我仅定义了一个参数，所以直接取第一个参数
        args = json.loads(tool_call.function.arguments)
        rel_data = love_relation(args["relations"])
        return rel_data
    return []


if __name__ == "__main__":
    text = "小龙喜欢小姚，但是小姚喜欢小王,小王喜欢小雪。"
    # text = 'ni hao '     # 测试无情感关系
    res = run_agent_with_toolcall(text)
    print("人物关系图谱")
    print(json.dumps(res, ensure_ascii=False, indent=4))
