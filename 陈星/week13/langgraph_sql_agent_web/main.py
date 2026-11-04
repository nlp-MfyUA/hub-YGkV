"""命令行入口：离线演示 / 在线 API / 显示图 / 状态快照。"""

import argparse
import json
from pathlib import Path

from brains import MockBrain, LLMBrain
from db_tools import SQLiteTools
from sql_graph import build_graph


def main():
    parser = argparse.ArgumentParser(description="LangGraph SQL Agent 教学复刻")
    parser.add_argument("question", nargs="*", help="自然语言问题")
    parser.add_argument("--mode", choices=["mock", "llm"], default="mock")
    parser.add_argument("--inject-typo", action="store_true", help="仅 mock：故意生成错误 SQL，演示修复回环")
    parser.add_argument("--stream", action="store_true", help="每执行一个节点打印 State 快照摘要")
    parser.add_argument("--mermaid", action="store_true", help="打印 LangGraph 自动生成的 Mermaid 图代码")
    args = parser.parse_args()

    question = " ".join(args.question).strip() or "哪位歌手拥有最多专辑？"
    db = SQLiteTools(Path(__file__).with_name("chinook.db"))
    brain = (
        MockBrain(inject_typo=args.inject_typo)
        if args.mode == "mock" else LLMBrain()
    )
    graph = build_graph(db, brain, max_repairs=3)

    if args.mermaid:
        print("=== 图的结构（Mermaid）===")
        print(graph.get_graph().draw_mermaid())

    input_state = {"question": question, "repair_count": 0, "trace": []}

    if args.stream:
        state = {}
        printed = 0
        # values 模式在每个节点之后提供一份新的 State 快照。
        for snapshot in graph.stream(input_state, stream_mode="values"):
            state = snapshot
            for event in state.get("trace", [])[printed:]:
                print("  ->", event)
                printed += 1
    else:
        state = graph.invoke(input_state)
        for event in state.get("trace", []):
            print("  ->", event)

    print("\\n=== 结果 ===")
    result = {
        "question": state["question"],
        "tables": state.get("tables", []),
        "sql": state.get("sql"),
        "answer": state.get("answer"),
        "shown_rows": state.get("shown_rows", 0),
        "truncated": state.get("truncated", False),
        "repair_count": state.get("repair_count", 0),
        "error": state.get("error") or None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
