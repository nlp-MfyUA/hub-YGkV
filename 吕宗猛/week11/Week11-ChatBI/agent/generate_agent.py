"""Agent A：结合数据库结构生成 SQL。

采用「收口工具」模式：模型必须调用 submit_sql 提交结果。
（网关不支持 response_format=json_schema，故不使用 output_type。）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from agents import Agent, ModelSettings, RunContextWrapper, StopAtTools, function_tool

import config
from core import executor, llm
from core import schema as schema_mod

_BASE_INSTRUCTIONS = """你是资深的 SQLite 数据分析师，负责把用户的自然语言问题翻译成一条可直接执行的只读查询。

数据库信息：
{schema}

工作方法：
1. 先判断问题涉及哪些表与字段；对字段名、取值没把握时，调用 describe_table / sample_values / search_text 核实，绝不凭印象拼写。
2. 多表查询必须沿上方列出的外键关系 JOIN，每条 JOIN 都要有明确的 ON 条件；禁止无 ON 的 JOIN 与 CROSS JOIN。
3. 中文提到的国家、城市、流派、媒体类型等在库中是英文（如 USA、Canada、Rock），先用 sample_values 确认真实取值再过滤。
4. 只允许 SELECT 或 WITH ... SELECT。任何写操作、DDL、PRAGMA 都会被系统拒绝并记为失败。

SQL 规范：
- 显式列出所需列，避免 SELECT *；列别名用英文 snake_case 且语义清晰（如 customer_count、total_revenue）。
- 聚合查询的 GROUP BY 必须覆盖所有非聚合列。
- TopN 必须同时写 ORDER BY 与 LIMIT；排序方向要符合问题语义。
- 日期以 TEXT 存储（'YYYY-MM-DD HH:MM:SS'），用 date(InvoiceDate) 或 BETWEEN '2021-01-01' AND '2021-12-31' 这类可比较写法。
- 金额用 ROUND(SUM(...), 2)；需要比例时先乘 1.0，避免整数除法截断。
- 不要给 SQL 加结尾分号。

完成后必须调用 submit_sql 提交，不要只用文字回答：
- sql：最终 SQL
- reasoning：一句话说明统计口径与关键取舍
- tables：实际用到的表名列表
"""


@dataclass
class SQLProposal:
    sql: str = ""
    reasoning: str = ""
    tables: list[str] = field(default_factory=list)
    fallback: bool = False


@dataclass
class GenerateContext:
    proposal: SQLProposal | None = None


@function_tool
def list_tables() -> str:
    """列出数据库中所有业务表及行数。"""
    info = schema_mod.get_schema()
    return info.table_directory()


@function_tool
def describe_table(table: str) -> str:
    """查看一张表的字段、类型、主键、外键与索引。

    Args:
        table: 表名，例如 customers。
    """
    info = schema_mod.get_schema()
    return info.describe(table)


@function_tool
def sample_values(table: str, column: str, limit: int = 8) -> str:
    """查看某字段的去重示例值，用于确认英文取值写法。

    Args:
        table: 表名。
        column: 字段名。
        limit: 返回条数，默认 8。
    """
    try:
        values = executor.sample_values(table, column, limit)
        return json.dumps(values, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return f"错误：{exc}"


@function_tool
def search_text(keyword: str) -> str:
    """在所有文本字段中模糊搜索关键字，用于确认用户提到的实体在库中的实际写法。

    Args:
        keyword: 关键字，例如 Berlin、AC/DC。
    """
    hits = executor.search_text(keyword)
    if not hits:
        return "未找到匹配文本"
    return json.dumps(hits, ensure_ascii=False)


@function_tool
def submit_sql(
    ctx: RunContextWrapper[GenerateContext],
    sql: str,
    reasoning: str,
    tables: list[str],
) -> str:
    """提交最终的只读 SQL。必须调用本工具作为最终答复。

    Args:
        sql: 一条可直接执行的 SQLite 查询语句。
        reasoning: 一句话说明统计口径与关键取舍。
        tables: 实际用到的表名列表。
    """
    ctx.context.proposal = SQLProposal(
        sql=(sql or "").strip(),
        reasoning=(reasoning or "").strip(),
        tables=[t for t in (tables or []) if isinstance(t, str)],
    )
    return "已接收"


_TOOLS = [list_tables, describe_table, sample_values, search_text, submit_sql]


def build_agent(schema: schema_mod.SchemaInfo | None = None) -> Agent:
    info = schema or schema_mod.get_schema()
    return Agent(
        name="sql_generator",
        instructions=_BASE_INSTRUCTIONS.format(schema=info.prompt()),
        model=llm.model(config.GENERATE_MODEL),
        tools=_TOOLS,
        tool_use_behavior=StopAtTools(stop_at_tool_names=["submit_sql"]),
        model_settings=ModelSettings(temperature=0.0, max_tokens=1200),
    )


def _fallback_extract(output: str) -> SQLProposal | None:
    """模型未调用收口工具时的兜底解析。"""
    text = (output or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:sql)?\s*(.+?)```", text, re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else text
    match = re.search(r"\b(with|select)\b.*", candidate, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return SQLProposal(
        sql=match.group(0).strip(),
        reasoning="模型未调用提交工具，已从文本中提取",
        fallback=True,
    )


async def generate_sql(
    question: str,
    feedback: str | None = None,
    *,
    agent: Agent | None = None,
) -> tuple[llm.AgentRun, SQLProposal | None]:
    agent = agent or build_agent()
    context = GenerateContext()
    payload = question if not feedback else f"{question}\n\n{feedback}"
    run = await llm.run_agent(agent, payload, context=context, max_turns=6)
    proposal = context.proposal
    if proposal is None and run.ok:
        proposal = _fallback_extract(str(run.output or ""))
    return run, proposal
