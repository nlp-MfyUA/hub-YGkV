from openai import OpenAI
import json

client = OpenAI(
    api_key="sk-be67532af78f4a97aba5cfe2a0830c34",
    base_url="https://api.deepseek.com",
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_relations",
            "description": "获取两人或者多人，两两之间的关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "person_list": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                        "description": "一个或者多个任务名称，用逗号分隔，例如：person1,person2,person3",
                    },
                    "desc_text": {
                        "type": "string",
                        "description": "任务之间的描述文本",
                    },
                },
                "required": ["person_list", "desc_text"],
            },
        },
    }
]

def get_messages(message):
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=message,
        tools=tools,
        tool_choice="auto",
        stream=False,
    )
    return response.choices[0].message

def get_relations(person_list,desc_text):
    person_str = ",".join(person_list)
    prompt = (f"""
    人物列表：{person_str}
    原始描述：{desc_text}
    任务：分析列表中所有人两两之间的关系。
    可选关系范围：[父子，母子，兄弟，兄妹，姐弟，姐妹，情侣，夫妻，爱慕，同事，同学，朋友，情敌，婆媳]
    规则：
    1. 只能使用上面给出的关系词汇，超出范围统一返回'不明确'
    2. 输出标准JSON数组，每条结构：{{"source":"人名","relation":"关系","target":"人名"}}
    3. 不要额外解释文字，只输出纯JSON
    4. 用户文本中出现的任务必须两两关系完全输出，如不明确请在关系位置输出’不明确‘
    5. 如人数为N，则需要输出N*(N-1)/2条关系，确保两两关系都输出
    """)
    result = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    return result.choices[0].message.content

if __name__ == '__main__':
    json_type = {
        "source": "string",
        "relation": "string",
        "target": "string"
    }
    system_prompt = (f"你是一个人物关系分析的助手，能够根据给定的描述文本，分析人物之间两两之间的关系。可选关系范围：[父子，母子，兄弟，兄妹，姐弟，姐妹，情侣，夫妻，爱慕，同事，同学，朋友，情敌，婆媳]"
                     f"如可选项中没有人物关系，则进行合理推测，如文本中无明确指向才能输出’不明确‘"
                     f"按照{json_type}的格式输出JSON数组"
                     f"如人数为N，则需要输出N*(N-1)/2条关系，确保两两关系都输出")
    while True:
        history = [{"role": "system", "content": system_prompt}]
        user_input = input("你：")
        user_message = {"role": "user", "content": user_input}
        history.append(user_message)
        while True:
            messages = get_messages(history)
            tools_output = messages.tool_calls
            #print("助手_tools_output：", tools_output)
            if tools_output:
                tool_call = tools_output[0]
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                history.append(messages.model_dump())
                #print("助手_messages：", messages.model_dump())
                if function_name == "get_relations":
                    result = get_relations(function_args["person_list"], function_args["desc_text"])
                else:
                    print(f"工具{function_name}调用失败")
                    break
                history.append({"role": "tool","tool_call_id":tool_call.id, "content": result})
            else:
                print("助手：", messages.content)
                break
