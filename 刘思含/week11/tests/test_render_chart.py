"""Tests for the chart rendering tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.tools.render_chart import render_chart, render_chart_payload

COLUMNS = ["severity", "count"]
ROWS = [["高危", 3], ["中危", 5], ["低危", 2]]


@pytest.fixture
def chart_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect chart output into a temporary directory."""
    monkeypatch.setenv("CHART_OUTPUT_ROOT", str(tmp_path / "charts"))
    monkeypatch.setenv("CHAT_SESSION_ID", "s1")
    return tmp_path / "charts"


def test_bar_chart(chart_env: Path) -> None:
    payload = json.loads(render_chart_payload(COLUMNS, ROWS, "bar"))
    assert payload["chart_type"] == "bar"
    option = payload["option"]
    assert option["xAxis"]["type"] == "category"
    assert option["xAxis"]["data"] == ["高危", "中危", "低危"]
    assert option["series"][0]["type"] == "bar"
    assert option["series"][0]["data"] == [3, 5, 2]


def test_pie_chart(chart_env: Path) -> None:
    payload = json.loads(render_chart_payload(COLUMNS, ROWS, "pie"))
    series = payload["option"]["series"][0]
    assert series["type"] == "pie"
    assert series["data"][0] == {"name": "高危", "value": 3}
    assert all(set(item) == {"name", "value"} for item in series["data"])


def test_invalid_chart_type_defaults_to_bar(chart_env: Path) -> None:
    payload = json.loads(render_chart_payload(COLUMNS, ROWS, "radar"))
    assert payload["chart_type"] == "bar"
    assert payload["option"]["series"][0]["type"] == "bar"


def test_empty_rows_returns_error(chart_env: Path) -> None:
    payload = json.loads(render_chart_payload(COLUMNS, [], "bar"))
    assert payload == {"error": "no data to render"}


def test_chart_file_is_written(
    chart_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHAT_SESSION_ID", "session-42")
    payload = json.loads(render_chart_payload(COLUMNS, ROWS, "line"))
    chart_path = Path(payload["chart_path"])
    assert chart_path.is_file()
    assert chart_path.parent == chart_env / "session-42"
    saved = json.loads(chart_path.read_text(encoding="utf-8"))
    assert saved["chart_type"] == "line"
    assert saved["option"] == payload["option"]


def test_line_chart(chart_env: Path) -> None:
    payload = json.loads(render_chart_payload(COLUMNS, ROWS, "line"))
    assert payload["option"]["series"][0]["type"] == "line"


def test_function_tool_wrapper() -> None:
    from agents import FunctionTool

    assert isinstance(render_chart, FunctionTool)
    assert render_chart.name == "render_chart"
    properties = render_chart.params_json_schema["properties"]
    assert set(properties) == {"columns", "rows", "chart_type"}
