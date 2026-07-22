"""
情感分析小模型 — 基于 Tool Calling 的人物关系提取
任务：用户输入"小明喜欢小姚，但是小姚喜欢小王"，模型返回人物关系图谱
"""

import json
from openai import OpenAI
from collections import defaultdict

client = OpenAI(
    api_key="sk-df327b1e08b14542a8723c02d3f94810",
    base_url="https://api.deepseek.com",
)

# ═════════════════════════════════════════════════════════════════════════════
# 工具函数：存储和展示人物关系
# ═════════════════════════════════════════════════════════════════════════════

relationship_graph = defaultdict(list)

def add_relationship(source: str, target: str, emotion: str, intensity: str = "中等") -> str:
    """添加一条人物关系记录

    Args:
        source: 源头人物（主动方）
        target: 目标人物（被动方）
        emotion: 情感类型，如 喜欢、爱慕、讨厌、尊敬 等
        intensity: 情感强度，如 轻微、中等、强烈
    """
    relationship_graph[source].append({
        "target": target,
        "emotion": emotion,
        "intensity": intensity
    })
    return f"已记录：{source} → {target} ({emotion}, {intensity})"


def get_relationship_graph() -> str:
    """获取当前所有人物关系"""
    if not relationship_graph:
        return "暂无关系记录"

    result = []
    for source, relations in relationship_graph.items():
        for rel in relations:
            result.append(f"{source} --[{rel['emotion']}/{rel['intensity']}]--> {rel['target']}")
    return "\n".join(result)


def clear_relationships() -> str:
    """清空所有关系记录"""
    relationship_graph.clear()
    return "已清空所有关系记录"


# ═════════════════════════════════════════════════════════════════════════════
# 工具描述 Schema（传给模型）
# ═════════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_relationship",
            "description": "添加一条人物情感关系记录，用于构建人物关系图谱",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "源头人物名称（主动方），如 小明",
                    },
                    "target": {
                        "type": "string",
                        "description": "目标人物名称（被动方），如 小姚",
                    },
                    "emotion": {
                        "type": "string",
                        "description": "情感类型，如 喜欢、爱慕、讨厌、尊敬、暗恋、仰慕 等",
                    },
                    "intensity": {
                        "type": "string",
                        "description": "情感强度等级",
                        "enum": ["轻微", "中等", "强烈", "极致"],
                    },
                },
                "required": ["source", "target", "emotion"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_relationship_graph",
            "description": "获取当前所有人物关系图谱",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_relationships",
            "description": "清空所有关系记录，开始新的分析",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

FUNCTION_MAP = {
    "add_relationship": add_relationship,
    "get_relationship_graph": get_relationship_graph,
    "clear_relationships": clear_relationships,
}


def run_tool_call(tc) -> str:
    """执行工具调用，返回结果"""
    name = tc.function.name
    args = json.loads(tc.function.arguments)
    print(f"    → 调用工具：{name}({json.dumps(args, ensure_ascii=False)})")
    result = FUNCTION_MAP[name](**args)
    print(f"    ← 结果：{result}")
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 可视化：打印人物关系图谱
# ═════════════════════════════════════════════════════════════════════════════

def print_relationship_graph_ascii():
    """用 ASCII 艺术打印人物关系图谱"""
    print("\n" + "=" * 60)
    print("           [人物关系图谱]")
    print("=" * 60)

    if not relationship_graph:
        print("  暂无关系记录")
        print("=" * 60)
        return

    # 收集所有人物
    all_persons = set(relationship_graph.keys())
    for relations in relationship_graph.values():
        for rel in relations:
            all_persons.add(rel["target"])

    print(f"\n  登场人物 ({len(all_persons)} 人): {', '.join(sorted(all_persons))}\n")
    print("  " + "-" * 56)

    # 打印关系
    for source, relations in relationship_graph.items():
        for rel in relations:
            # 使用简单符号代替 emoji
            arrow = {"喜欢": "[喜欢]", "爱慕": "[爱慕]", "讨厌": "[讨厌]", "尊敬": "[尊敬]",
                     "暗恋": "[暗恋]", "仰慕": "[仰慕]", "关心": "[关心]", "保护": "[保护]"}.get(rel["emotion"], "->")
            intensity_bar = {"轻微": "--", "中等": "--->", "强烈": "----->", "极致": "=======>"}.get(rel["intensity"], "--->")
            print(f"  {source} {intensity_bar} {rel['target']}  {arrow}")

    print("  " + "-" * 56)

    # 分析复杂关系
    print("\n  关系分析:")

    # 找到被最多人喜欢的人
    loved_count = defaultdict(list)
    for source, relations in relationship_graph.items():
        for rel in relations:
            loved_count[rel["target"]].append(source)

    most_loved = max(loved_count.items(), key=lambda x: len(x[1]), default=(None, []))
    if most_loved[0]:
        print(f"    * 最受欢迎：{most_loved[0]} (被 {len(most_loved[1])} 人喜欢)")

    # 找到单向箭头（单恋）
    print("    * 单向关系（单恋）:")
    has_single = False
    for source, relations in relationship_graph.items():
        for rel in relations:
            target = rel["target"]
            # 检查是否有反向关系
            has_reverse = False
            if target in relationship_graph:
                for r in relationship_graph[target]:
                    if r["target"] == source and r["emotion"] in ["喜欢", "爱慕", "暗恋"]:
                        has_reverse = True
                        break
            if not has_reverse and rel["emotion"] in ["喜欢", "爱慕", "暗恋"]:
                has_single = True
                print(f"      - {source} -> {target} (单向箭头)")

    if not has_single:
        print("      (无单向关系)")

    print("=" * 60)


# ═════════════════════════════════════════════════════════════════════════════
# 主函数：分析用户输入的人物关系
# ═════════════════════════════════════════════════════════════════════════════

def analyze_relationships(user_input: str):
    """分析用户输入文本中的人物关系"""

    print(f"\n用户输入：{user_input}")
    print("\n模型分析中...\n")

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个人物关系分析助手。你的任务是从用户的描述中提取所有人物之间的情感关系。"
                "请仔细分析文本，识别出所有的人物对和他们之间的情感关系。"
                "对于每一对关系，调用 add_relationship 工具来记录："
                "- source: 主动方（喜欢别人的人）"
                "- target: 被动方（被喜欢的人）"
                "- emotion: 情感类型（喜欢、爱慕、暗恋、讨厌、尊敬等）"
                "- intensity: 情感强度（轻微、中等、强烈、极致），根据上下文判断"
                "提取完所有关系后，调用 get_relationship_graph 来展示完整的关系图谱。"
            )
        },
        {"role": "user", "content": user_input},
    ]

    # 循环处理工具调用 - 逐个执行，避免并行工具调用问题
    max_turns = 10
    for turn in range(max_turns):
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
            temperature=0.1,
        )

        msg = response.choices[0].message

        if msg.tool_calls:
            # 每次只处理第一个 tool_call，然后重新调用 API
            # 这样可以避免 DeepSeek 对并行工具调用的限制
            tc = msg.tool_calls[0]
            result = run_tool_call(tc)

            # 追加 assistant 消息和 tool 消息
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
        else:
            if msg.content:
                print(f"  模型分析：{msg.content}")
            break

    return get_relationship_graph()


# ═════════════════════════════════════════════════════════════════════════════
# 主程序
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 修复 Windows 控制台编码问题
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("      情感分析小模型 - 人物关系提取")
    print("=" * 60)
    print("\n功能：分析文本中的人物情感关系，生成关系图谱")
    print("示例输入：小明喜欢小姚，但是小姚喜欢小王")
    print("输入 'quit' 退出程序\n")

    while True:
        try:
            user_input = input("请输入人物关系描述：").strip()
        except EOFError:
            print("\n再见！")
            break

        if user_input.lower() in ["quit", "exit", "q"]:
            print("\n再见！")
            break

        if not user_input:
            print("输入不能为空，请重新输入\n")
            continue

        # 清空之前的记录
        clear_relationships()

        # 分析关系
        analyze_relationships(user_input)

        # 打印关系图谱
        print_relationship_graph_ascii()
        print()
