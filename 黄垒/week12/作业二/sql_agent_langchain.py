"""作业二：用 LangChain 复刻 OpenAI Agents 版的 SQL Agent。

和 week11 的 7 段式 Workflow 相比，这次是「Agent 自主编排工具」：
模型自己决定先看哪些表、取哪些 schema、SQL 报错后怎么改，代码只提供工具和安全边界。

运行：
    python sql_agent_langchain.py --demo
    python sql_agent_langchain.py "每个国家的客户数量是多少？"
    python sql_agent_langchain.py -i                    # 多轮交互（带记忆）
    python sql_agent_langchain.py --no-trace "..."      # 只看最终答案
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from langchain.agents import create_agent  # noqa: E402
from langchain.agents.middleware import ModelCallLimitMiddleware  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from db_parser import DBParser  # noqa: E402
from prompts import FOLLOW_UP_HINT, SYSTEM_PROMPT, USER_TEMPLATE  # noqa: E402
from toolkit import SQLToolkit, ToolEvent  # noqa: E402

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class LangChainSQLAgent:
    def __init__(
        self,
        db_path: str | Path,
        trace: bool = True,
        max_steps: int = 12,
    ) -> None:
        self.parser = DBParser(db_path)
        self.trace = trace
        self.toolkit = SQLToolkit(
            parser=self.parser,
            on_event=self._on_tool_event if trace else None,
        )
        self.tools = self.toolkit.as_tools()
        self.agent = create_agent(
            model=_build_model(),
            tools=self.tools,
            system_prompt=SYSTEM_PROMPT.format(catalog=self._catalog_summary()),
            middleware=[
                # 防止模型陷入「改 SQL -> 报错 -> 再改」的死循环
                ModelCallLimitMiddleware(run_limit=max_steps),
            ],
            checkpointer=InMemorySaver(),
        )

    # ------------------------------------------------------------------ #
    # 对外
    # ------------------------------------------------------------------ #
    def run(self, question: str, thread_id: str = "cli", follow_up: bool = False) -> str:
        self.toolkit.executed.clear()
        self.toolkit.events.clear()

        prompt = USER_TEMPLATE.format(question=question)
        if follow_up:
            prompt = prompt + "\n\n" + FOLLOW_UP_HINT

        config = {"configurable": {"thread_id": thread_id}}
        messages: list = []

        if self.trace:
            print("    思考中…")

        for chunk in self.agent.stream(
            {"messages": [HumanMessage(content=prompt)]},
            config=config,
            stream_mode="updates",
        ):
            for node, payload in chunk.items():
                for message in payload.get("messages", []) if isinstance(payload, dict) else []:
                    messages.append(message)
                    self._print_model_message(node, message)

        answer = self._final_answer(messages)
        self._print_report(question, answer)
        return answer

    def close(self) -> None:
        self.parser.close()

    def __enter__(self) -> "LangChainSQLAgent":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 输出
    # ------------------------------------------------------------------ #
    def _catalog_summary(self) -> str:
        counts = self.parser.row_counts
        return "\n".join(
            f"- {table}（{counts[table]} 行）" for table in self.parser.table_names
        )

    def _on_tool_event(self, event: ToolEvent) -> None:
        preview = event.result.replace("\n", " ")
        if len(preview) > 150:
            preview = preview[:147] + "..."
        args = ", ".join(f"{k}={_short(v)}" for k, v in event.args.items())
        print(f"    [工具] {event.name}({args})  ({event.elapsed:.2f}s)")
        print(f"           -> {preview}")

    def _print_model_message(self, node: str, message) -> None:
        if not self.trace:
            return
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                print(f"    [模型] 调用 {call['name']}：{_short(call.get('args', {}))}")
            if message.content and not message.tool_calls:
                print("    [模型] 生成最终回答")
        elif isinstance(message, ToolMessage):
            pass  # 工具结果已经由 _on_tool_event 打印

    def _final_answer(self, messages: list) -> str:
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content and not message.tool_calls:
                return _content_to_text(message.content)
        # 没有最终回答时，给出可诊断的信息
        if self.toolkit.executed and not self.toolkit.executed[-1].ok:
            return f"没能完成查询：{self.toolkit.executed[-1].error}"
        return "模型没有生成最终回答，可能是达到最大步数限制，请重试或换个问法。"

    def _print_report(self, question: str, answer: str) -> None:
        if not self.trace:
            print(f"\n问题：{question}\n回答：{answer}")
            return

        print("\n" + "-" * 64)
        print(f"问题：{question}")
        if self.toolkit.executed:
            print("执行的 SQL：")
            for index, item in enumerate(self.toolkit.executed, 1):
                flag = "✓" if item.ok else "✗"
                detail = f"{item.rows} 行" if item.ok else item.error[:80]
                print(f"  {index}. {flag} {item.sql.replace(chr(10), ' ')[:120]}")
                print(f"     -> {detail}  ({item.elapsed:.2f}s)")
        else:
            print("执行的 SQL：（无，模型没有调用 run_sql）")
        print(f"回答：{answer}")
        print("-" * 64)


def _build_model() -> ChatOpenAI:
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY，请先把 .env.example 复制为 .env 并填入自己的 Key。")

    return ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL") or None,
        temperature=0,
        timeout=120,
        max_retries=2,
    )


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return str(content)


def _short(value, limit: int = 100) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


DEMO_QUESTIONS = [
    "每个国家的客户数量是多少？按客户数从多到少排序，取前 5 个。",
    "销售额最高的 5 位客户是谁？请给出客户姓名和总消费金额。",
    "Rock 类型的歌曲一共有多少首？",
    "每位艺术家的专辑数量，取前 3 名。",
    "2009 年每个月的总销售额是多少？",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="LangChain 版 SQL Agent（chinook.db）")
    parser.add_argument("question", nargs="?", help="自然语言问题")
    parser.add_argument("--demo", action="store_true", help="跑内置的 5 个演示问题")
    parser.add_argument("-i", "--interactive", action="store_true", help="多轮交互模式")
    parser.add_argument("--db", default=str(BASE_DIR / "chinook.db"), help="sqlite 数据库路径")
    parser.add_argument("--no-trace", action="store_true", help="不打印工具调用过程")
    parser.add_argument("--thread", default="cli", help="会话 ID，交互模式下用于保存上下文")
    parser.add_argument("--max-steps", type=int, default=12, help="模型最大调用轮数")
    args = parser.parse_args()

    if not (args.question or args.demo or args.interactive):
        parser.print_help()
        return

    try:
        agent = LangChainSQLAgent(args.db, trace=not args.no_trace, max_steps=args.max_steps)
    except RuntimeError as exc:
        print(f"启动失败：{exc}")
        return

    with agent:
        print(f"数据库：{args.db}（{len(agent.parser.table_names)} 张表）")
        print(f"模型：{os.environ.get('LLM_MODEL', 'deepseek-chat')}，工具：list_tables / get_schema / run_sql")

        if args.demo:
            for index, question in enumerate(DEMO_QUESTIONS, 1):
                print(f"\n{'=' * 64}\n[{index}/{len(DEMO_QUESTIONS)}]")
                # 演示用例彼此独立，每问开一个新会话，避免上下文串味
                agent.run(question, thread_id=f"demo-{index}")
            return

        if args.question:
            agent.run(args.question, thread_id=args.thread)
            return

        # 交互模式：同一个 thread_id，模型能看到历史对话，支持「那 2010 年呢？」这类追问
        print("输入问题，空行退出。同一会话内支持追问。")
        first = True
        while True:
            try:
                question = input("\n你：").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question:
                break
            agent.run(question, thread_id=args.thread, follow_up=not first)
            first = False


if __name__ == "__main__":
    main()
