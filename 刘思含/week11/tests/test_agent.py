"""Agent orchestration tests using a scripted fake model (no real LLM)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from agents import Runner
from agents.items import ToolCallItem, ToolCallOutputItem
from agents.models.interface import Model, ModelResponse, ModelTracing
from agents.usage import Usage
from openai.types.responses import ResponseOutputMessage, ResponseOutputText

from app.agent.definition import vuln_analyst


class ScriptedModel(Model):
    """Model that replays a fixed sequence of scripted turns."""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.seen_inputs: list[Any] = []

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing: ModelTracing,
        *,
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
        **kwargs,
    ) -> ModelResponse:
        self.seen_inputs.append(input)
        step = self.script.pop(0) if self.script else {"text": ""}
        if "tools" in step:
            outputs = [tool_call(name, args) for name, args in step["tools"]]
            return ModelResponse(output=outputs, usage=Usage(), response_id=None)
        return ModelResponse(
            output=[assistant_text(step["text"])], usage=Usage(), response_id=None
        )

    def stream_response(self, *args, **kwargs):  # pragma: no cover - unused
        raise NotImplementedError


def assistant_text(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="msg-1",
        content=[ResponseOutputText(text=text, type="output_text", annotations=[])],
        role="assistant",
        status="completed",
        type="message",
    )


def tool_call(name: str, arguments: dict[str, Any]) -> Any:
    from openai.types.responses import ResponseFunctionToolCall

    return ResponseFunctionToolCall(
        id=f"call-{name}",
        call_id=f"call-{name}",
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
        type="function_call",
    )


def _tool_names(result: Any) -> list[str]:
    return [
        item.raw_item.name
        for item in result.new_items
        if isinstance(item, ToolCallItem)
    ]


@pytest.mark.asyncio
async def test_statistics_with_knowledge_hit(monkeypatch) -> None:
    from app.tools import search_knowledge as kb

    monkeypatch.setattr(
        kb,
        "search_knowledge_payload",
        lambda question: json.dumps(
            {
                "hit": True,
                "kb_entry_id": 1,
                "sql_template": (
                    "SELECT COUNT(*) FROM v_vulnerability WHERE severity='高危'"
                ),
                "params_schema": None,
            },
            ensure_ascii=False,
        ),
    )

    model = ScriptedModel(
        [
            {"tools": [("search_knowledge", {"question": "高危漏洞有多少"})]},
            {
                "tools": [
                    (
                        "execute_sql",
                        {
                            "sql": (
                                "SELECT COUNT(*) FROM v_vulnerability "
                                "WHERE severity='高危'"
                            )
                        },
                    )
                ]
            },
            {
                "text": (
                    "共有 5 个高危漏洞。SQL 如下："
                    "SELECT COUNT(*) FROM v_vulnerability WHERE severity='高危'"
                )
            },
        ]
    )
    agent = vuln_analyst.clone(model=model)
    result = await Runner.run(agent, "高危漏洞有多少")
    assert _tool_names(result) == ["search_knowledge", "execute_sql"]
    assert "5" in result.final_output
    assert "SELECT COUNT(*)" in result.final_output
    outputs = [
        str(item.output)
        for item in result.new_items
        if isinstance(item, ToolCallOutputItem)
    ]
    assert any('"ok": false' in output or "ok" in output for output in outputs)


@pytest.mark.asyncio
async def test_statistics_without_knowledge_hit(monkeypatch) -> None:
    from app.tools import search_knowledge as kb

    monkeypatch.setattr(
        kb,
        "search_knowledge_payload",
        lambda question: json.dumps({"hit": False}, ensure_ascii=False),
    )
    import app.tools.get_schema as gs

    monkeypatch.setattr(
        gs,
        "get_schema_payload",
        lambda: json.dumps({"tables": {}, "type_catalog": []}),
    )
    import app.tools.execute_sql as exec_mod

    monkeypatch.setattr(
        exec_mod,
        "execute_sql_query",
        lambda sql: json.dumps(
            {"ok": True, "columns": ["c"], "rows": [[3]], "row_count": 1, "sql": sql}
        ),
    )
    model = ScriptedModel(
        [
            {"tools": [("search_knowledge", {"question": "按类型分布"})]},
            {"tools": [("get_schema", {})]},
            {
                "tools": [
                    (
                        "execute_sql",
                        {
                            "sql": "SELECT type_name, COUNT(*) FROM v_vulnerability GROUP BY type_name"
                        },
                    )
                ]
            },
            {"text": "按类型分布结果见 SQL。"},
        ]
    )
    agent = vuln_analyst.clone(model=model)
    result = await Runner.run(agent, "按漏洞类型分布")
    assert _tool_names(result) == ["search_knowledge", "get_schema", "execute_sql"]


@pytest.mark.asyncio
async def test_image_detail_question(monkeypatch) -> None:
    import app.tools.search_image_evidence as sie

    monkeypatch.setattr(
        sie,
        "search_image_evidence_payload",
        lambda vuln_name=None, keywords=None, limit=10: json.dumps(
            {
                "hit": True,
                "count": 1,
                "items": [
                    {
                        "source_file": "a.pdf",
                        "source_page": 3,
                        "image_index": 1,
                        "image_path": "abc/3_1.png",
                        "image_type": "screenshot",
                        "ocr_text": "GET /api?id=1' OR 1=1-- HTTP/1.1",
                        "ocr_text_truncated": False,
                        "ocr_confidence": "high",
                        "linked_vuln_name": "SQL 注入",
                    }
                ],
                "query_used": '"payload"',
            },
            ensure_ascii=False,
        ),
    )
    model = ScriptedModel(
        [
            {
                "tools": [
                    (
                        "search_image_evidence",
                        {"vuln_name": "SQL 注入", "keywords": ["payload"]},
                    )
                ]
            },
            {
                "text": (
                    "以下为 OCR 识别内容：\n```\nGET /api?id=1' OR 1=1-- HTTP/1.1\n```\n"
                    "图片：abc/3_1.png，请核对原图。OCR 可能存在识别误差，以原图为准。"
                )
            },
        ]
    )
    agent = vuln_analyst.clone(model=model)
    result = await Runner.run(agent, "SQL 注入的 payload 是什么")
    assert _tool_names(result) == ["search_image_evidence"]
    assert "OR 1=1" in result.final_output
    assert "abc/3_1.png" in result.final_output
    assert "核对原图" in result.final_output


@pytest.mark.asyncio
async def test_image_not_found(monkeypatch) -> None:
    import app.tools.search_image_evidence as sie

    monkeypatch.setattr(
        sie,
        "search_image_evidence_payload",
        lambda vuln_name=None, keywords=None, limit=10: json.dumps(
            {"hit": False, "count": 0}, ensure_ascii=False
        ),
    )
    model = ScriptedModel(
        [
            {
                "tools": [
                    (
                        "search_image_evidence",
                        {"vuln_name": "SQL 注入", "keywords": ["payload"]},
                    )
                ]
            },
            {"text": "未找到该漏洞的图片证据。"},
        ]
    )
    agent = vuln_analyst.clone(model=model)
    result = await Runner.run(agent, "SQL 注入的 payload 是什么")
    assert "未找到" in result.final_output
    assert "OR 1=1" not in result.final_output


@pytest.mark.asyncio
async def test_out_of_scope_request() -> None:
    model = ScriptedModel([{"text": "拒绝：该请求涉及写操作，我只能执行只读查询。"}])
    agent = vuln_analyst.clone(model=model)
    result = await Runner.run(agent, "把表删了")
    assert _tool_names(result) == []
    assert "拒绝" in result.final_output


def test_agent_definition_shape() -> None:
    assert vuln_analyst.name == "VulnerabilityAnalyst"
    assert {tool.name for tool in vuln_analyst.tools} == {
        "get_schema",
        "search_knowledge",
        "execute_sql",
        "search_image_evidence",
        "render_chart",
    }
    assert "v_image_evidence_fts" in vuln_analyst.instructions
