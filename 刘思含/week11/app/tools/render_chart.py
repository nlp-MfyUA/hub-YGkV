"""Chart rendering tool: returns an ECharts option and persists it."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from agents import function_tool

VALID_CHART_TYPES = ("bar", "pie", "line")
DEFAULT_CHART_TYPE = "bar"
DEFAULT_SESSION = "default"


def _charts_dir(session_id: str) -> Path:
    """Return the output directory for persisted chart options.

    ``CHART_OUTPUT_ROOT`` lets tests redirect output; the default is the
    project's chart directory.
    """
    root = Path(os.environ.get("CHART_OUTPUT_ROOT", "data/charts"))
    return root / session_id


def _error(message: str) -> str:
    """Serialize an error response."""
    return json.dumps({"error": message}, ensure_ascii=False)


def _build_option(
    chart_type: str, columns: list[str], rows: list[list[Any]]
) -> dict[str, Any]:
    """Build an ECharts option for the requested chart type."""
    categories = [row[0] for row in rows]
    values = [row[1] if len(row) > 1 else None for row in rows]
    if chart_type == "pie":
        return {
            "tooltip": {"trigger": "item"},
            "legend": {"data": [str(category) for category in categories]},
            "series": [
                {
                    "type": "pie",
                    "radius": "60%",
                    "data": [
                        {"name": str(category), "value": value}
                        for category, value in zip(categories, values)
                    ],
                }
            ],
        }
    if chart_type == "line":
        return {
            "tooltip": {"trigger": "axis"},
            "legend": {"data": [columns[1] if len(columns) > 1 else "value"]},
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": columns[1] if len(columns) > 1 else "value",
                    "data": values,
                }
            ],
        }
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [columns[1] if len(columns) > 1 else "value"]},
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "bar",
                "name": columns[1] if len(columns) > 1 else "value",
                "data": values,
            }
        ],
    }


def render_chart_payload(
    columns: list[str],
    rows: list[list[Any]],
    chart_type: str = DEFAULT_CHART_TYPE,
) -> str:
    """将查询结果渲染为 ECharts option JSON，并落盘到图表目录。

    参数必须严格使用 columns / rows / chart_type 三个字段。
    不要传 xAxis / yAxis / values / data 等字段——它们属于 ECharts option
    内部结构，不是本工具的入参。

    columns: 列名列表。第一列为分类（x 轴 / 饼图 name），第二列为数值。
    rows: 行数据列表，每行是与 columns 对齐的数组，例如 [["高危", 28]]。
    chart_type: 图表类型，取值 bar / pie / line（默认 bar，非法值回退 bar）。

    正确示例（柱状图）：
      render_chart(
        columns=["severity", "count"],
        rows=[["高危", 28], ["中危", 14], ["低危", 4]],
        chart_type="bar",
      )

    正确示例（饼图）：
      render_chart(
        columns=["severity", "count"],
        rows=[["高危", 28], ["中危", 14], ["低危", 4]],
        chart_type="pie",
      )

    错误示例（不要这样传）：
      render_chart(xAxis=["高危"], yAxis=[28])
      render_chart(values=[28, 14, 4])
      render_chart(data=[{"name": "高危", "value": 28}])
    """
    if not rows:
        return _error("no data to render")
    normalized_type = (
        chart_type if chart_type in VALID_CHART_TYPES else DEFAULT_CHART_TYPE
    )
    option = _build_option(normalized_type, list(columns or []), rows)
    payload = {
        "chart_type": normalized_type,
        "option": option,
    }
    try:
        session_id = os.environ.get("CHAT_SESSION_ID", DEFAULT_SESSION)
        output_dir = _charts_dir(session_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        chart_path = output_dir / f"{timestamp}.json"
        chart_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        payload["chart_path"] = chart_path.as_posix()
    except OSError as exc:
        payload["chart_path"] = None
        payload["chart_path_error"] = str(exc)
    return json.dumps(payload, ensure_ascii=False)


render_chart = function_tool(render_chart_payload, name_override="render_chart")
