"""
============================================================================
作业2: 借助于 LLM Tool Call 或 JSON Mode 能力，构建简单情感分析智能体
============================================================================

功能描述：
    输入一段自然语言文本，利用大模型的结构化输出能力，
    自动提取人物之间的情感关系，输出为 JSON 格式的关系图谱。

技术方案：
    - 方案A: JSON Mode（response_format 强制 JSON 输出）
    - 方案B: Tool Call（函数调用，模型按 schema 返回结构化参数）

环境要求：
    pip install openai python-dotenv

使用方式：
    1. 在同目录下创建 .env 文件，配置：
       DEEPSEEK_API_KEY=sk-xxxxx
       DEEPSEEK_BASE_URL=https://api.deepseek.com
       DEEPSEEK_MODEL=deepseek-chat
    2. 运行: python 作业2_情感分析智能体.py
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

# ============================================================================
# 第一部分：环境配置
# ============================================================================

# 加载 .env 文件中的环境变量
load_dotenv()

# 从环境变量中读取 API 配置
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 创建 OpenAI 兼容客户端（DeepSeek 使用 OpenAI 协议）
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


# ============================================================================
# 第二部分：方案A - JSON Mode 实现
# ============================================================================

def analyze_with_json_mode(text: str) -> list[dict]:
    """
    使用 JSON Mode 提取文本中的人物情感关系。

    原理：
        通过设置 response_format={"type": "json_object"}，
        强制模型输出合法的 JSON 格式，避免夹杂多余文字。

    参数：
        text: 待分析的自然语言文本

    返回：
        关系三元组列表，如 [{"source": "小明", "relation": "爱慕", "target": "小姚"}]
    """

    # 系统提示词：定义角色 + 输出格式约束
    system_prompt = """你是一个专业的人物关系分析专家。你的任务是从用户输入的文本中，提取所有人物之间的情感关系。

请严格按照以下 JSON 格式输出：
{
    "relationships": [
        {
            "source": "发出情感的人物",
            "relation": "情感关系类型",
            "target": "接收情感的人物"
        }
    ]
}

关系类型(relation)请从以下词汇中选择最合适的：
爱慕、喜欢、讨厌、暗恋、追求、崇拜、嫉妒、信任、依赖、关心

注意：
1. 必须提取文本中所有的人物关系，不要遗漏
2. 只输出 JSON，不要输出任何其他文字
3. 如果文本中没有明确的情感关系，返回空数组"""

    # 用户消息：传入待分析的文本
    user_message = f"请分析以下文本中的人物情感关系：\n\n{text}"

    # 调用大模型 API，开启 JSON Mode
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        # 关键参数：强制模型输出 JSON 格式
        response_format={"type": "json_object"},
        temperature=0.1,  # 低温度，让输出更稳定确定
    )

    # 提取模型返回的文本内容
    raw_content = response.choices[0].message.content

    # 解析 JSON 字符串为 Python 对象
    try:
        result = json.loads(raw_content)
        return result.get("relationships", [])
    except json.JSONDecodeError as e:
        print(f"[JSON Mode] 解析失败: {e}")
        print(f"[JSON Mode] 原始返回: {raw_content}")
        return []


# ============================================================================
# 第三部分：方案B - Tool Call 实现
# ============================================================================

def analyze_with_tool_call(text: str) -> list[dict]:
    """
    使用 Tool Call（函数调用）提取文本中的人物情感关系。

    原理：
        预先定义一个"工具"及其参数 schema，
        模型会按照 schema 生成结构化的函数调用参数，
        比 JSON Mode 有更严格的格式约束。

    参数：
        text: 待分析的自然语言文本

    返回：
        关系三元组列表
    """

    # 定义工具（函数）的 JSON Schema
    # 这告诉模型："你有一个工具可以调用，参数必须符合这个结构"
    tools = [
        {
            "type": "function",
            "function": {
                "name": "extract_relationships",
                "description": "从文本中提取人物之间的情感关系，返回关系三元组列表",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relationships": {
                            "type": "array",
                            "description": "人物情感关系列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source": {
                                        "type": "string",
                                        "description": "发出情感的人物名称",
                                    },
                                    "relation": {
                                        "type": "string",
                                        "description": "情感关系类型，如：爱慕、喜欢、讨厌、暗恋、追求、崇拜、嫉妒、信任、依赖、关心",
                                    },
                                    "target": {
                                        "type": "string",
                                        "description": "接收情感的人物名称",
                                    },
                                },
                                "required": ["source", "relation", "target"],
                            },
                        }
                    },
                    "required": ["relationships"],
                },
            },
        }
    ]

    # 系统提示词（Tool Call 模式下可以更简洁，因为格式由 schema 约束）
    system_prompt = "你是一个人物关系分析专家。请从用户输入的文本中提取所有人物之间的情感关系，使用提供的工具输出结果。"

    user_message = f"请分析以下文本中的人物情感关系：\n\n{text}"

    # 调用大模型 API，传入 tools 定义
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        tools=tools,
        # 强制模型必须调用工具（而非自由回复）
        tool_choice={"type": "function", "function": {"name": "extract_relationships"}},
        temperature=0.1,
    )

    # 从 tool_calls 中提取函数调用参数
    message = response.choices[0].message

    # 检查模型是否确实调用了工具
    if message.tool_calls:
        # 获取第一个工具调用的参数（JSON 字符串）
        arguments_str = message.tool_calls[0].function.arguments
        try:
            arguments = json.loads(arguments_str)
            return arguments.get("relationships", [])
        except json.JSONDecodeError as e:
            print(f"[Tool Call] 参数解析失败: {e}")
            print(f"[Tool Call] 原始参数: {arguments_str}")
            return []
    else:
        print("[Tool Call] 模型未调用工具，返回内容为:")
        print(message.content)
        return []


# ============================================================================
# 第四部分：结果展示
# ============================================================================

def print_relationships(relationships: list[dict], method_name: str):
    """格式化打印人物关系图谱"""
    print(f"\n{'='*50}")
    print(f"  分析方式: {method_name}")
    print(f"{'='*50}")

    if not relationships:
        print("  未提取到人物关系。")
        return

    print(f"  共提取到 {len(relationships)} 条关系：\n")
    for i, rel in enumerate(relationships, 1):
        source = rel.get("source", "?")
        relation = rel.get("relation", "?")
        target = rel.get("target", "?")
        print(f"  {i}. {source} ——[{relation}]——> {target}")

    # 输出标准 JSON 格式
    print(f"\n  JSON 输出:")
    print(f"  {json.dumps(relationships, ensure_ascii=False, indent=4)}")


# ============================================================================
# 第五部分：主程序入口
# ============================================================================

def main():
    """主函数：演示两种方案的效果"""

    # 检查 API Key 是否配置
    if not API_KEY:
        print("错误：未配置 DEEPSEEK_API_KEY！")
        print("请在同目录下创建 .env 文件，内容如下：")
        print("  DEEPSEEK_API_KEY=sk-xxxxx")
        print("  DEEPSEEK_BASE_URL=https://api.deepseek.com")
        print("  DEEPSEEK_MODEL=deepseek-chat")
        return

    # 测试文本（作业要求的输入）
    test_text = "小明喜欢小姚，但是小姚喜欢小王。"

    print(f"输入文本: {test_text}")
    print(f"使用模型: {MODEL}")

    # --- 方案A: JSON Mode ---
    print("\n>>> 正在使用 JSON Mode 分析...")
    result_json_mode = analyze_with_json_mode(test_text)
    print_relationships(result_json_mode, "JSON Mode")

    # --- 方案B: Tool Call ---
    print("\n>>> 正在使用 Tool Call 分析...")
    result_tool_call = analyze_with_tool_call(test_text)
    print_relationships(result_tool_call, "Tool Call")

    # --- 额外测试：更复杂的文本 ---
    print("\n\n" + "#" * 50)
    print("  额外测试：复杂文本")
    print("#" * 50)

    complex_text = "张三暗恋李四，李四和王五是好朋友，但张三嫉妒王五，因为李四总是关心王五。"
    print(f"\n输入文本: {complex_text}")

    result_complex = analyze_with_tool_call(complex_text)
    print_relationships(result_complex, "Tool Call (复杂文本)")


if __name__ == "__main__":
    main()
