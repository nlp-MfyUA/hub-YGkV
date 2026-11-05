"""
冒烟测试：验证 LangGraph 图的两条「非直线」路径。

    A. 多轮记忆：同一 thread_id 下连续追问，选表 / 生成能沿用上下文；
    B. 校验 -> 改写：注入一条写错字段的 SQL，观察条件边把流程送回改写节点。

运行：
    python smoke_test.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sql_graph import SQLAgentGraph, print_result  # noqa: E402

DB_PATH = Path(__file__).with_name("chinook.db")


def multi_turn_demo() -> None:
    print("=" * 68)
    print("A. 多轮记忆：同一 thread_id 连续追问")
    print("=" * 68)

    thread_id = f"smoke-{uuid.uuid4().hex[:8]}"
    questions = [
        "Rock 类型的歌曲一共有多少首？",
        "那 Pop 呢？",
        "这两种类型加起来一共多少首？",
    ]

    with SQLAgentGraph(DB_PATH) as agent:
        for question in questions:
            print(f"\n>>> {question}")
            print_result(agent.run(question, thread_id=thread_id, trace=True))


def rewrite_demo() -> None:
    print("\n" + "=" * 68)
    print("B. 校验 -> 改写闭环：第一次生成故意写错字段")
    print("=" * 68)

    with SQLAgentGraph(DB_PATH, inject_bad_sql=True) as agent:
        question = "Rock 类型的歌曲一共有多少首？"
        print(f"\n>>> {question}")
        result = agent.run(question, thread_id=uuid.uuid4().hex, trace=True)
        print_result(result)
        print(
            f"\n校验记录：共 {len(result.attempts)} 次生成/改写，"
            + " -> ".join(
                f"第{item['attempt']}次{'通过' if item['ok'] else '失败'}"
                for item in result.attempts
            )
        )


if __name__ == "__main__":
    multi_turn_demo()
    rewrite_demo()
