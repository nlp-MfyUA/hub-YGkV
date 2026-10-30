"""Agent C：把查询结果归纳成中文答案，并把 token 增量流式回传。

无工具的纯生成任务，直接用 ChatOpenAI.astream() 做流式输出（langchain 标准
用法）；思维链内容在 additional_kwargs 里，不推给前端（与原版只推
output_text.delta 的行为一致）。
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import config
from core import llm as llm_mod
from core import schema as schema_mod
from core.executor import QueryResult

_INSTRUCTIONS = """你是一名业务数据分析师。用户提出了一个问题，系统已经查出数据，你要把数据翻译成一到几句中文结论。

输出要求：
- 直接回答用户的问题：第一句就给出结论与关键数字（谁、多少、排名如何）。
- 只陈述数据事实，不解释数据是怎么算出来的，也不评价问题本身。
- 只输出简体中文正文：不要代码块、不要表格、不要罗列列名，不要出现「查询」「语句」「字段」这类词。
- 数据为空时，写「该条件下没有数据」，并给出一条最可能的原因。
- 金额保留两位小数；比例写成百分数；全文不超过 200 字。
- 排名类问题：用「- 」列出前 5 名（名称 + 数值），其余用一句话概括。
"""


def _table_text(result: QueryResult, max_rows: int = 6, max_chars: int = 1600) -> str:
    lines = [" | ".join(result.columns)]
    for index, row in enumerate(result.rows[:max_rows], start=1):
        cells = ["NULL" if value is None else str(value) for value in row]
        lines.append(f"{index}. " + " | ".join(cells))
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已截断）"
    return text


def build_payload(question: str, result: QueryResult) -> str:
    shown = min(len(result.rows), 6)
    note = f"结果说明：共 {result.row_count} 行"
    if result.truncated:
        note += "（已达到行数上限，仅覆盖部分数据，回答时必须注明「仅基于前 N 行」）"
    note += f"。下面列出其中前 {shown} 行。"
    return "\n".join(
        [
            f"用户问题：{question}",
            note,
            "已知数据范围：",
            schema_mod.get_schema().temporal_text(),
            "结果数据（第一行为列名）：",
            _table_text(result),
            "请用 2-4 句简体中文直接回答上面的问题：第一句给出结论与关键数字；"
            "不要使用表格，不要逐项罗列超过 5 项，不要提到查询语句或字段名；"
            "若未达到行数上限，不必说明只看到部分行。",
        ]
    )


async def stream_summary(
    question: str,
    result: QueryResult,
    *,
    llm: Any | None = None,
) -> AsyncIterator[dict]:
    llm = llm or llm_mod.model(config.SUMMARY_MODEL, temperature=0.0, max_tokens=1000)
    payload = build_payload(question, result)
    text_parts: list[str] = []
    usage: dict = {}
    error: str | None = None
    try:
        async for chunk in llm.astream(
            [("system", _INSTRUCTIONS), ("human", payload)]
        ):
            delta = _chunk_text(chunk)
            if delta:
                text_parts.append(delta)
                yield {"type": "delta", "text": delta}
            if getattr(chunk, "usage_metadata", None):
                usage = llm_mod.usage_dict(chunk.usage_metadata)
    except Exception as exc:  # noqa: BLE001 - 流式中断也要给出可展示信息
        error = f"{type(exc).__name__}: {exc}"
    yield {
        "type": "done",
        "text": "".join(text_parts),
        "usage": usage,
        "error": error,
    }


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)
