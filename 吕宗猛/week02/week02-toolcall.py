import time
from openai import OpenAI
import json
import dotenv, os

dotenv.load_dotenv(override=True)

AGNES_BASE_URL = os.getenv("AGNES_BASE_URL")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")
AGNES_MODEL_NAME = os.getenv("AGNES_MODEL_NAME")


def get_relation_list(relations_str: str) -> list[dict]:
    """
    关系列表转换
    此函数仅为本地函数调用测试,将关系列表参数，原样返回
    :param relations_str: 关系字符串,多个关系以','间隔,格式为:人A-关系-人B,人A-关系-人B
    :return:
    """
    if not relations_str:
        return []
    else:
        relations_arr = relations_str.split(',')
        relation_list = []
        for single_relation in relations_arr:
            sub_str = single_relation.split('-')
            if len(sub_str) == 3:
                relation_list.append({"name": sub_str[0], "relation": sub_str[1], "target": sub_str[2]})
        return relation_list


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_relation_list",
            "description": "关系列表转换",
            "parameters": {
                "type": "object",
                "properties": {
                    "relations_str": {
                        "type": "string",
                        "description": "关系字符串,多个关系以','间隔,格式为:人A-关系-人B,人A-关系-人B",
                    }
                },
                "required": ["relations_str"],
            },
        },
    }
]

# 工具名 → 本地函数映射
FUNCTION_MAP = {
    "get_relation_list": get_relation_list
}


def run_tool_call(tc) -> list[dict]:
    name = tc.function.name
    args_dict = json.loads(tc.function.arguments)
    print(f'  -> 调用工具:{name},参数为:{json.dumps(args_dict, ensure_ascii=False)}')
    result = FUNCTION_MAP[name](**args_dict)
    print(f'  <- 工具返回:{name},结果为:{result}')
    return result


print('\n' + '*' * 30)
print('大模型调用本地工具')
client = OpenAI(
    api_key=AGNES_API_KEY,
    base_url=AGNES_BASE_URL
)

message_list = [
    {"role": "system",
     "content": "你是一位专业的情感专家,根据用户输入的关系说明，得到说明中的人物之间的关系。可根据需要调用工具返回人物关系."},
    {"role": "user", "content": "小明喜欢小姚，但是小姚喜欢小王"},
]

start_time = time.time()
response = client.chat.completions.create(
    model=AGNES_MODEL_NAME,
    messages=message_list,
    tools=TOOLS,
    temperature=0.0,
    stream=False
)

choice = response.choices[0]
msg = choice.message

if msg.tool_calls:
    for tc in msg.tool_calls:
        result = run_tool_call(tc)

        message_list.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False)  # 转成字符串
        })
        message_list.append({"role": "user", "content": "请把工具返回结果使用json对象返回"})

    final_response = client.chat.completions.create(
        model=AGNES_MODEL_NAME,
        messages=message_list,
        tools=TOOLS,
        temperature=0.0,
        stream=False
    )
    end_time = time.time()
    usage_obj = final_response.usage

    print(f'此次总结,总耗时:{(end_time - start_time):.3f}秒,消耗token详情如下:')
    print(f'  -> 总token:{usage_obj.total_tokens}')
    print(f'  -> 输入token:{usage_obj.prompt_tokens}')
    print(f'  -> 输出token:{usage_obj.completion_tokens}')
    print(f'最终回复:\n{final_response.choices[0].message.content}')
else:
    print(f'直接回复:{msg}')
