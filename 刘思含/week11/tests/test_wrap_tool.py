"""Tests for ``app.main._wrap_tool``.

Regression guard for [AGENT-003]: rebuilding the tool with
``function_tool(invoke, ...)`` derived the parameter schema from
``invoke(context, arguments)``, so every LLM call failed validation with
``ModelBehaviorError: Invalid JSON input for tool <name>``.
"""

from __future__ import annotations

import asyncio
import json

from agents.tool_context import ToolContext

from app.main import _ToolRecorder, _wrap_tool
from app.tools.execute_sql import execute_sql


def _ctx(tool_name: str, arguments: str) -> ToolContext:
    return ToolContext(
        context=None,
        usage=None,
        tool_name=tool_name,
        tool_call_id="test-call",
        tool_arguments=arguments,
    )


def test_wrap_tool_preserves_params_schema() -> None:
    recorder = _ToolRecorder()
    wrapped = _wrap_tool(execute_sql, recorder)

    assert wrapped.params_json_schema == execute_sql.params_json_schema
    assert "sql" in wrapped.params_json_schema["properties"]
    # The wrapper must not leak its own (context, arguments) signature.
    assert "context" not in wrapped.params_json_schema["properties"]
    assert "arguments" not in wrapped.params_json_schema["properties"]


def test_wrap_tool_keeps_identity_and_policy() -> None:
    recorder = _ToolRecorder()
    wrapped = _wrap_tool(execute_sql, recorder)

    assert wrapped.name == execute_sql.name
    assert wrapped.description == execute_sql.description
    assert wrapped.strict_json_schema == execute_sql.strict_json_schema
    assert wrapped.on_invoke_tool is not execute_sql.on_invoke_tool


def test_wrap_tool_records_arguments() -> None:
    recorder = _ToolRecorder()
    wrapped = _wrap_tool(execute_sql, recorder)
    arguments = json.dumps({"sql": "SELECT COUNT(*) AS n FROM v_type_catalog"})

    # on_tool_start is what the agents runtime calls before invoking the tool;
    # it appends the (name, "", None) placeholder that _wrap_tool fills in.
    async def _run() -> str:
        await recorder.on_tool_start(None, None, wrapped)
        return await wrapped.on_invoke_tool(_ctx("execute_sql", arguments), arguments)

    output = asyncio.run(_run())

    assert recorder.calls, "recorder should have one entry"
    name, recorded_args, recorded_result = recorder.calls[-1]
    assert name == "execute_sql"
    assert recorded_args == arguments
    assert recorded_result == output
    # The tool really ran and returned JSON (not the SDK failure message).
    assert "An error occurred while running the tool" not in str(output)
