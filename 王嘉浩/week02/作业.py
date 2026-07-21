import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-wbkddimxwtgnfujavaysryupyxxhmwtbjwxgnnbixpysffdb",
    base_url="https://api.siliconflow.cn/v1",
)

#定义辅助函数，json解析函数
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
        

system_prompt = """
从用户的文字描述中提取所有的人物关系信息，以 JSON 格式输出，包含以下字段：
- name: 姓名
- relationship: 关系描述
- name2: 相关人物姓名

JSON 输出示例：
[
    {"name": "张三","relationship": "喜欢", "name2": "李四"}，
    {"name": "李四","relationship": "喜欢","name2": "王五"}
]
"""

user_prompt = """
小明喜欢小姚，但是小姚喜欢小王
"""

response = client.chat.completions.create(
    model="Pro/deepseek-ai/DeepSeek-V3.2",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    response_format={"type": "json_object"},
    temperature=0.0,
    #reasoning_effort="high",
    #extra_body={"thinking": {"type": "enabled"}},
)


content = response.choices[0].message.content
result = safe_json_parse(content)

if result:
    # 兼容外层是 {"items": [...]} 或直接数组
    items = result if isinstance(result, list) else result.get("items", result.get("relationships", [result]))
    print(f"\n共提取 {len(items)} 个关系:")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item['name']} — {item['relationship']} ({item['name2']})")
    print(f"\n原始输出:\n{json.dumps(result, ensure_ascii=False, indent=2)}")

print()
