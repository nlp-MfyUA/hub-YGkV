import json
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI




# 1 加载环境
load_dotenv("llm.deepseek.env")

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# 2 解析输出
def json_parse(str):
    if not str or not str.strip():
        print("ERR:模型返回了空内容")
        return None
    return json.loads(str)

# 3 构建智能体函数
def extract_relationships(str):
    prompt =  """
你是一个人物关系分析专家。从用户提供的文本中提取所有人物之间的关系。

以 JSON 格式输出，key 为 "relationships"，value 是一个数组。
数组中的每个元素包含三个字段：
- source:   关系的发起方（人名）
- relation: 关系类型（中文，如：爱慕、讨厌、喜欢、暗恋、是朋友、是夫妻、是同事、是师生等）
- target:   关系的接收方（人名）

注意：
1. 只提取明确的人物关系，不要臆测
2. 人名保持原文
3. 关系类型用简洁的中文词
4. 如果没有检测到任何关系，返回空数组 {"relationships": []}

输出示例：
{"relationships": [{"source": "小明", "relation": "爱慕", "target": "小姚"}]}
"""

    print(f"正在分析{str}\n")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": str},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,  # 低温度保证稳定性
        max_tokens=2000,
    )

    content = response.choices[0].message.content
    result = json_parse(content)

    if result is None:
        print("ERR:JSON 解析失败\n")
        return []

    return result.get("relationships", [])

# ── 4. 展示结果 ──────────────────────────────────────────
def print_relationships(relationships):
    if not relationships:
        print("未检测到任何人物关系\n")
        return

    print(f" 共检测到 {len(relationships)} 条关系：\n")
    for i, rel in enumerate(relationships, 1):
        source = rel.get("source", "?")
        relation = rel.get("relation", "?")
        target = rel.get("target", "?")
        arrow = "──" if len(relation) <= 2 else "─"
        print(f"  {i}. {source} {arrow}『{relation}』{arrow} {target}")

    # 打印 JSON 格式（
    print(f"JSON 输出格式:")
    print(json.dumps(relationships, ensure_ascii=False, indent=4))
    print()

# ── 5. 主程序 ────────────────────────────────────────────
if __name__ == "__main__":

    text1 = "小明喜欢小姚，但是小姚喜欢小王。"
    rels1 = extract_relationships(text1)
    print_relationships(rels1)

    #

    text2 = (
        "张三和李四是大学同学，毕业后一起创业。"
        "张三暗恋王五，但王五已经是李四的女朋友了。"
        "赵六是他们的大学老师，一直很欣赏张三的才华。"
    )
    rels2 = extract_relationships(text2)
    print_relationships(rels2)

    while True:
        user_input = input("\n请输入描述人物关系的文本: ").strip()
        if user_input.lower() in ("q", "quit", "exit"):
            print("再见！")
            break
        if not user_input:
            continue
        rels = extract_relationships(user_input)
        print_relationships(rels)
