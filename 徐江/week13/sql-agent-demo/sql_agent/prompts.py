"""所有发给 LLM 的 prompt 模板（LangChain ChatPromptTemplate）+ 模型输出解析工具。

week11 版是「手拼 messages 字典 + 函数」；week12 版改为 LangChain 的
``ChatPromptTemplate``：system/human 消息与模板变量分离，由 LCEL 链
（``prompt | model | parser``）在运行时格式化。

四个模板对应四个需要 LLM 的阶段：
- SELECT_TABLES_PROMPT  Table 选择
- GENERATE_SQL_PROMPT   SQL 生成
- REWRITE_SQL_PROMPT    SQL 改写
- SUMMARIZE_PROMPT     结果汇总

``TASK_KEYWORDS`` 是各 system prompt 的特征词，供 MockChatModel 分派任务
（见 llm.py），与 dev/mock_openai_server.py 的分派思路一致。
"""
from __future__ import annotations

import json
import re

from langchain_core.prompts import ChatPromptTemplate

from .models import ExecutionResult

# ============================================================ Table 选择
SELECT_TABLES_SYSTEM = """你是一个数据库专家，擅长判断一个自然语言问题需要查询哪些表。

给定数据库的表结构和一个问题，请选出回答该问题所必需的表。
只返回如下 JSON，不要输出任何其他内容：

{{"tables": ["表名1", "表名2"], "reason": "一句话说明选择理由"}}

注意：
- 只选必需的表，宁缺毋滥；通过外键能关联到的表才需要选；
- 表名必须与给定结构中的表名完全一致。"""

SELECT_TABLES_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SELECT_TABLES_SYSTEM),
    ("human", "数据库包含以下表：\n\n{schema_prompt}\n\n问题：{question}"),
])


# ============================================================ SQL 生成
GENERATE_SQL_SYSTEM = """你是一个严谨的 SQLite 数据分析专家。根据用户问题和给定的数据库结构，编写一条正确的 SQL 查询。

硬性规则：
1. 只输出一条 SELECT 查询（可以是 WITH 开头的 CTE），严禁任何写操作；
2. 只能使用给定的表和列，禁止猜测不存在的表名、列名；
3. 字符串字面量必须用单引号，例如 '已完成'；
4. 日期列是 'YYYY-MM-DD' 格式的文本，直接按字符串比较即可；
5. 先一句话说明思路，然后输出一个 ```sql 代码块，代码块内只有一条 SQL，以分号结尾。"""

GENERATE_SQL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", GENERATE_SQL_SYSTEM),
    ("human", "数据库结构：\n\n{schema_prompt}\n\n问题：{question}"),
])


# ============================================================ SQL 改写
REWRITE_SQL_SYSTEM = """你是一个 SQLite 专家。下面这条 SQL 未通过校验或执行失败，请根据错误信息修复它。

修复要点：
1. 仔细核对错误信息中指出的表名 / 列名，与给定结构比对；
2. 常见问题：列名拼写错误、遗漏 JOIN、在 WHERE 中误用聚合函数、GROUP BY 不完整；
3. 只输出修复后的 SQL，格式为一个 ```sql 代码块，不要输出解释。"""

REWRITE_SQL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", REWRITE_SQL_SYSTEM),
    ("human", (
        "数据库结构：\n\n{schema_prompt}\n\n"
        "问题：{question}\n\n"
        "之前的 SQL：\n```sql\n{failed_sql}\n```\n\n"
        "错误信息：{error}\n\n"
        "这是第 {attempt} 次尝试，请修复上面的 SQL。"
    )),
])


# ============================================================ 结果汇总
SUMMARIZE_SYSTEM = """你是一个数据分析师。根据用户问题、执行的 SQL 和查询结果，用简体中文写一段简洁的结论。

要求：
1. 2-4 句话，直接回答用户问题，必须包含关键数字；
2. 如果结果为空，明确说明“没有符合条件的数据”；
3. 不要复述 SQL，不要使用 Markdown 标题。"""

SUMMARIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SUMMARIZE_SYSTEM),
    ("human", (
        "问题：{question}\n\n"
        "执行的 SQL：\n```sql\n{sql}\n```\n\n"
        "查询结果（共 {row_count} 行{truncated_note}，列：{columns}，"
        "最多展示 {shown_count} 行）：\n{result_preview}"
    )),
])


def build_summarize_input(question: str, sql: str, execution: ExecutionResult,
                          *, preview_rows: int = 15) -> dict:
    """把执行结果格式化成 SUMMARIZE_PROMPT 的模板变量（week11 的
    build_summarize_messages 拆分版：模板管结构，本函数管数据预处理）。"""
    shown = execution.rows[:preview_rows]
    body = "\n".join(str(row) for row in shown) if shown else "（无数据）"
    note = "，已截断" if execution.truncated else ""
    return {
        "question": question,
        "sql": sql,
        "row_count": execution.row_count,
        "truncated_note": note,
        "columns": execution.columns,
        "shown_count": len(shown),
        "result_preview": body,
    }


# ============================================================ 任务特征词
# MockChatModel 按 system prompt 中的特征词分派模拟任务（与 mock_openai_server 一致）
TASK_KEYWORDS = {
    "select_tables": "数据库专家",          # SELECT_TABLES_SYSTEM 首句
    "generate_sql": "数据分析专家",          # GENERATE_SQL_SYSTEM 首句
    "rewrite_sql": "修复",                  # REWRITE_SQL_SYSTEM 正文
    "summarize": "数据分析师",               # SUMMARIZE_SYSTEM 首句
}


# ============================================================ 输出解析工具
def extract_sql(text: str) -> str:
    """从模型输出中提取 SQL：优先取 ```sql 代码块，退化到首个 SELECT/WITH 开头片段。"""
    if not text:
        return ""
    m = re.search(r"```(?:sqlite|sql)?\s*\n(.*?)```", text, re.S | re.I)
    if m:
        sql = m.group(1)
    else:
        m2 = re.search(r"(?is)\b(with|select)\b.*", text)
        if not m2:
            return ""
        sql = m2.group(0)
    sql = sql.strip()
    while sql.endswith(";"):
        sql = sql[:-1].strip()
    return sql


def extract_json(text: str) -> dict | None:
    """从模型输出中提取第一个 JSON 对象。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


__all__ = [
    "SELECT_TABLES_PROMPT", "GENERATE_SQL_PROMPT", "REWRITE_SQL_PROMPT",
    "SUMMARIZE_PROMPT", "build_summarize_input", "TASK_KEYWORDS",
    "extract_sql", "extract_json",
]
