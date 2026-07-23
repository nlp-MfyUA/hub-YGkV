from openai import OpenAI
import json

client = OpenAI(
    base_url="https://api.minimaxi.com/v1",
    api_key="sk-cp-mEeFZRSWbWzFdg5og740Eac0Lu1fZGO2yo_O2EBqleWlXqT7JOM51DnnL76FaTz9wgKgwiwb74QAj8ujsXgsJ2QHvkrbVAjRb4QVCpYSJzDLDTSS2rF0dWw"
)

print("="*50)
print("1、调用本地工具，输出结果")
print("="*50)

#===================
#定义本地工具函数
#===================

def get_relation(text: str) -> list:
    """分析人物建的关系"""
    relation =[]
    if not text:
        return relation
    #查找表达情感的字符
    start = 0
    while True:
        idx = text.find('喜欢',start)
        if idx == -1:
            break
        relation.append({"source":text[idx-2:idx],"relation":"爱慕","target":text[idx+2:idx+4]})
        start = idx + 1
    return relation


#===================
#工具描述
#===================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_relation",
            "description": "查询人物关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "包含情感的语句内容，如喜欢，爱，爱慕等",
                    },
                },
                "required": ["text"],
            },
        },
    }
]

#工具名 -> 本地函数映射
FUNCTION_MAP = {
    "get_relation":get_relation
}

#===================
#工具调用
#===================

messages = [
    {"role": "system", "content": "你是智能人物关系分析助手，可根据需要使用工具回答用户问题。当前日期：2026-07-22。"},
    {"role": "user", "content": "帮我分析一下这句话中的人物关系：小明喜欢小桃，但是小桃喜欢小王。"},
]


response = client.chat.completions.create(
    model="MiniMax-M3",
    tools=TOOLS,
    messages=messages,
    extra_body={"reasoning_split":True}
)

msg = response.choices[0].message


#模型返回工具调用
if msg.tool_calls:
    tc = msg.tool_calls[0]
    fcname = tc.function.name
    args = json.loads(tc.function.arguments)
    print(f"    → 调用工具: {fcname}({json.dumps(args, ensure_ascii=False)})")
    result = FUNCTION_MAP[fcname](**args)
    messages.append(msg)
    messages.append({
        "role":"tool",
        "tool_call_id":tc.id,
        "content":result,
    })
    

    #把工具结果发回模型，让其生成最终回复
    final = client.chat.completions.create(
        model="MiniMax-M3",
        tools=TOOLS,
        messages=messages,
        extra_body={"reasoning_split":True}
    )
    print(f"\n最终回复:{final.choices[0].message.content}")
else:
    print(f"直接回复:{msg.content}")




print("="*50)
print("2、使用json mode输出结果")
print("="*50)


#===========
#辅助函数
#===========
def safe_json_pares(text:str) -> dict|list|None:
    """安全解析 JSON，处理可能的空 content 和格式异常。"""
    if not text or not text.strip():
        print(f"    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        #尝试修复常见问题：删除 markdown 代码块标记
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    原始内容: {text[:200]}")
            return None

#==============
#JSON 模式输出
#==============

system_prompt = """
你是一个情感分析助手，请从用户的文字描述中提取人物关系，已 JSON 数组格式输出，包含以下字段：
- source:源姓名（关系里的源的姓名）
- relation:关系（喜欢、爱慕、爱等）
- target:目标姓名（关系的对象姓名）

JSON 输出示例：
[
    {"source":"张三","relation":"爱慕","target":"李四"},
    {"source":"李四","relation":"爱慕","target":"王五"}
]
"""

user_prompt = "小明喜欢小桃，但是小桃喜欢小王。"

response = client.chat.completions.create(
    model="MiniMax-M3",
    response_format={"type":"json_object"},
    messages=[
        {"role":"system","content":system_prompt},
        {"role":"user","content":user_prompt},
    ],
    extra_body={"reasoning_split": True},
)

content = response.choices[0].message.content
print(f"content:{content}")
result = safe_json_pares(content)
print(f"result1111:{result}")

if result:
    # 兼容外层是 {"items": [...]} 或直接数组
    items = result if isinstance(result, list) else result.get("items",result.get("products",[result]))
    print(f"\n共提取 {len(items)} 份人物关系:")
    print(f"\n原始输出:\n{json.dumps(result,ensure_ascii=False,indent=2)}")


