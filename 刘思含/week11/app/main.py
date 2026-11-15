"""CLI entry point for the ChatBI agent."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import asyncio  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from agents import Agent, RunHooks, Runner, function_tool  # noqa: E402

from app.agent.definition import vuln_analyst  # noqa: E402
from app.session import get_session  # noqa: E402

LOGGER = logging.getLogger("app.main")

DEFAULT_DB_PATH = Path("app/db/vuln.db")
DEFAULT_SESSION_DIR = Path(os.environ.get("SESSION_DIR", "data"))


@dataclass
class ToolTrace:
    """One tool invocation recorded during a run."""

    name: str
    arguments: str
    output: str


@dataclass
class ChatResult:
    """Answer plus the tools that were invoked."""

    answer: str
    traces: list[ToolTrace] = field(default_factory=list)


def _configure_db(db_path: Path) -> None:
    """Point the tools at the requested database."""
    os.environ["VULN_DB_PATH"] = str(Path(db_path))


def _trace_output(output: Any) -> str:
    """Normalize a tool output into text."""
    if isinstance(output, str):
        return output
    return json.dumps(output, ensure_ascii=False, default=str)


def _parse_arguments(tool_input: Any) -> str:
    """Return the JSON arguments text passed to a tool."""
    if isinstance(tool_input, str):
        return tool_input
    return json.dumps(tool_input, ensure_ascii=False, default=str)


class _ToolRecorder(RunHooks):
    """Record tool calls and their outputs for CLI display."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        self.calls.append((getattr(tool, "name", "unknown"), "", None))

    async def on_tool_end(
        self, context: Any, agent: Any, tool: Any, result: str
    ) -> None:
        # Arguments are written by the tool wrapper (on_tool_start does not
        # receive them in agents 0.1.0). Preserve them here instead of
        # overwriting with an empty string.
        if self.calls:
            name, arguments, _ = self.calls[-1]
            self.calls[-1] = (name, arguments, result)

    def traces(self) -> list[ToolTrace]:
        return [
            ToolTrace(name=name, arguments=args, output=_trace_output(output))
            for name, args, output in self.calls
        ]


def _wrap_tool(tool: Any, recorder: "_ToolRecorder") -> Any:
    """Wrap a FunctionTool so the CLI can show its arguments.

    Only ``on_invoke_tool`` is replaced; everything else (name, description,
    ``params_json_schema``, guardrails, timeout) is copied from the original
    tool. Rebuilding the tool via ``function_tool(invoke, ...)`` derived the
    parameter schema from ``invoke(context, arguments)``, so every LLM tool
    call failed validation with ``ModelBehaviorError: Invalid JSON input``.
    """
    original = tool.on_invoke_tool

    async def invoke(context: Any, arguments: str) -> Any:
        output = await original(context, arguments)
        if recorder.calls:
            name, _, result = recorder.calls[-1]
            # on_tool_end has not run yet; record the output now.
            recorder.calls[-1] = (name, arguments, result if result is not None else output)
        return output

    wrapped = copy.copy(tool)
    wrapped.on_invoke_tool = invoke
    return wrapped


def _agent_with_recorder(recorder: "_ToolRecorder") -> Agent:
    """Clone the analyst with wrapped tools for tracing."""
    wrapped = [_wrap_tool(tool, recorder) for tool in vuln_analyst.tools]
    return vuln_analyst.clone(tools=wrapped)


async def chat_once(
    user_id: str,
    question: str,
    db_path: Path | None = None,
    with_history: bool = True,
) -> ChatResult:
    """Run one question through the agent and persist the turn."""
    db_path = Path(db_path or os.environ.get("VULN_DB_PATH") or DEFAULT_DB_PATH)
    _configure_db(db_path)
    session = get_session(user_id, DEFAULT_SESSION_DIR)
    prompt = question
    if with_history and session.recent_turns():
        history = session.history_text()
        prompt = f"历史对话：\n{history}\n\n新问题：{question}"
    hooks = _ToolRecorder()
    agent = _agent_with_recorder(hooks)
    os.environ["CHAT_SESSION_ID"] = user_id
    result = await Runner.run(agent, prompt, hooks=hooks)
    answer = str(result.final_output)
    session.add_turn(question, answer)
    return ChatResult(answer=answer, traces=hooks.traces())


def _print_result(question: str, result: ChatResult, elapsed: float) -> None:
    """Print a readable answer block."""
    print("=" * 70)
    print(f"问题：{question}")
    print("-" * 70)
    print(result.answer)
    print("-" * 70)
    if result.traces:
        print("工具调用：")
        for trace in result.traces:
            print(f"  - {trace.name}({trace.arguments})")
            print(f"    -> {trace.output[:300]}")
    print(f"耗时：{elapsed:.2f}s")
    print("=" * 70)


async def _run_cli(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path or os.environ.get("VULN_DB_PATH") or DEFAULT_DB_PATH)
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 1
    _configure_db(db_path)
    if args.question:
        start = time.perf_counter()
        try:
            result = await chat_once(args.user, args.question, db_path)
        except Exception as exc:  # noqa: BLE001 - CLI should report, not crash
            LOGGER.error("chat_once failed: %s", exc, exc_info=True)
            print(f"调用失败：{exc}", file=sys.stderr)
            return 1
        _print_result(args.question, result, time.perf_counter() - start)
        return 0
    if args.interactive:
        print("交互模式：输入 exit 退出")
        while True:
            try:
                question = input("你> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question or question.lower() in ("exit", "quit"):
                break
            start = time.perf_counter()
            try:
                result = await chat_once(args.user, question, db_path)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                LOGGER.error("chat_once failed: %s", exc, exc_info=True)
                print(f"调用失败：{exc}")
                continue
            _print_result(question, result, time.perf_counter() - start)
        return 0
    print("请提供 --question 或 --interactive", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )
    parser = argparse.ArgumentParser(description="ChatBI-Vuln agent CLI")
    parser.add_argument("--question", "-q", help="single question")
    parser.add_argument("--interactive", "-i", action="store_true")
    parser.add_argument("--user", default="local")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args(argv)
    return asyncio.run(_run_cli(args))


if __name__ == "__main__":
    raise SystemExit(main())
