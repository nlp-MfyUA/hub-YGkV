"""Agent A：结合数据库结构生成 SQL（langchain create_agent 版）。

框架自动调度工具；模型调用收口工具 submit_sql 后把结果写入本请求独立的
store 容器，Agent 结束后从这里提取（等价于原 openai-agents 版的
RunContextWrapper + StopAtTools 语义）。
网关不支持 response_format=json_schema，仍保留文本解析兜底。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool

import config
from core import executor
from core import llm as llm_mod
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
- 禁止使用 PRAGMA 语句与 pragma_* 表值函数（如 pragma_table_info、pragma_index_list）：只读安全策略会在执行期拒绝它们。表结构信息已在上方提供，需要字段细节时用 describe_table 工具。
- 不要给 SQL 加结尾分号。

完成流程：先用辅助工具核实信息，然后调用 submit_sql 提交，最后直接输出「提交完成」结束，不要再调用任何工具。

submit_sql 参数：
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
class GenerateAgent:
    """一次请求内的生成 Agent：模型、工具、收口容器打包在一起。"""

    llm: Any
    store: dict
    tools: list
    system_prompt: str


def build_agent(schema: schema_mod.SchemaInfo | None = None) -> GenerateAgent:
    info = schema or schema_mod.get_schema()
    store: dict = {"proposal": None}

    # ---- 辅助工具：框架自动调度，模型自主决定调用时机 ----
    @tool
    def list_tables() -> str:
        """列出数据库中所有业务表及行数。"""
        return schema_mod.get_schema().table_directory()

    @tool
    def describe_table(table: str) -> str:
        """查看一张表的字段、类型、主键、外键与索引。

        Args:
            table: 表名，例如 customers。
        """
        return schema_mod.get_schema().describe(table)

    @tool
    def sample_values(table: str, column: str, limit: int = 8) -> str:
        """查看某字段的去重示例值，用于确认英文取值写法。

        Args:
            table: 表名。
            column: 字段名。
            limit: 返回条数，默认 8。
        """
        try:
            import json

            values = executor.sample_values(table, column, limit)
            return json.dumps(values, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return f"错误：{exc}"

    @tool
    def search_text(keyword: str) -> str:
        """在所有文本字段中模糊搜索关键字，用于确认用户提到的实体在库中的实际写法。

        Args:
            keyword: 关键字，例如 Berlin、AC/DC。
        """
        import json

        hits = executor.search_text(keyword)
        if not hits:
            return "未找到匹配文本"
        return json.dumps(hits, ensure_ascii=False)

    # ---- 收口工具：结果写入 store，Agent 结束后提取 ----
    @tool
    def submit_sql(sql: str, reasoning: str, tables: list[str]) -> str:
        """提交最终的只读 SQL。必须调用本工具作为最终答复。

        Args:
            sql: 一条可直接执行的 SQLite 查询语句。
            reasoning: 一句话说明统计口径与关键取舍。
            tables: 实际用到的表名列表。
        """
        store["proposal"] = SQLProposal(
            sql=(sql or "").strip(),
            reasoning=(reasoning or "").strip(),
            tables=[t for t in (tables or []) if isinstance(t, str)],
        )
        return "已接收：最终提交已保存。请直接输出「提交完成」结束，不要再调用任何工具。"

    return GenerateAgent(
        llm=llm_mod.model(config.GENERATE_MODEL, temperature=0.0, max_tokens=1200),
        store=store,
        tools=[list_tables, describe_table, sample_values, search_text, submit_sql],
        system_prompt=_BASE_INSTRUCTIONS.format(schema=info.prompt()),
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
    agent: GenerateAgent | None = None,
) -> tuple[llm_mod.AgentRun, SQLProposal | None]:
    gen = agent or build_agent()
    payload = question if not feedback else f"{question}\n\n{feedback}"
    run = await llm_mod.run_agent(
        gen.llm,
        name="sql_generator",
        system_prompt=gen.system_prompt,
        user_input=payload,
        tools=gen.tools,
        max_turns=6,
    )
    proposal = gen.store.get("proposal")
    if proposal is None and run.ok:
        proposal = _fallback_extract(str(run.output or ""))
    return run, proposal
