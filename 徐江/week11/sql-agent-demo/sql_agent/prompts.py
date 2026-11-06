"""所有发给 LLM 的 prompt 模板 + 模型输出的解析工具。

集中管理 prompt，便于演示时逐条讲解、也便于后续调整。
"""
from __future__ import annotations

import json
import re

# ============================================================ Table 选择
SELECT_TABLES_SYSTEM = """你是一个数据库专家，擅长判断一个自然语言问题需要查询哪些表。

给定数据库的表结构和一个问题，请选出回答该问题所必需的表。
只返回如下 JSON，不要输出任何其他内容：

{"tables": ["表名1", "表名2"], "reason": "一句话说明选择理由"}

注意：
- 只选必需的表，宁缺毋滥；通过外键能关联到的表才需要选；
- 表名必须与给定结构中的表名完全一致。"""


def build_select_tables_messages(schema_prompt: str, question: str) -> list[dict]:
    return [
        {"role": "system", "content": SELECT_TABLES_SYSTEM},
        {"role": "user", "content": f"数据库包含以下表：\n\n{schema_prompt}\n\n问题：{question}"},
    ]


# ============================================================ SQL 生成
GENERATE_SQL_SYSTEM = """你是一个严谨的 SQLite 数据分析专家。根据用户问题和给定的数据库结构，编写一条正确的 SQL 查询。

硬性规则：
1. 只输出一条 SELECT 查询（可以是 WITH 开头的 CTE），严禁任何写操作；
2. 只能使用给定的表和列，禁止猜测不存在的表名、列名；
3. 字符串字面量必须用单引号，例如 '已完成'；
4. 日期列是 'YYYY-MM-DD' 格式的文本，直接按字符串比较即可；
5. 先一句话说明思路，然后输出一个 ```sql 代码块，代码块内只有一条 SQL，以分号结尾。"""


def build_generate_messages(schema_prompt: str, question: str) -> list[dict]:
    return [
        {"role": "system", "content": GENERATE_SQL_SYSTEM},
        {"role": "user", "content": f"数据库结构：\n\n{schema_prompt}\n\n问题：{question}"},
    ]


# ============================================================ SQL 改写
REWRITE_SQL_SYSTEM = """你是一个 SQLite 专家。下面这条 SQL 未通过校验或执行失败，请根据错误信息修复它。

修复要点：
1. 仔细核对错误信息中指出的表名 / 列名，与给定结构比对；
2. 常见问题：列名拼写错误、遗漏 JOIN、在 WHERE 中误用聚合函数、GROUP BY 不完整；
3. 只输出修复后的 SQL，格式为一个 ```sql 代码块，不要输出解释。"""


def build_rewrite_messages(schema_prompt: str, question: str,
                           failed_sql: str, error: str, attempt: int) -> list[dict]:
    return [
        {"role": "system", "content": REWRITE_SQL_SYSTEM},
        {"role": "user", "content": (
            f"数据库结构：\n\n{schema_prompt}\n\n"
            f"问题：{question}\n\n"
            f"之前的 SQL：\n```sql\n{failed_sql}\n```\n\n"
            f"错误信息：{error}\n\n"
            f"这是第 {attempt} 次尝试，请修复上面的 SQL。"
        )},
    ]


# ============================================================ 结果汇总
SUMMARIZE_SYSTEM = """你是一个数据分析师。根据用户问题、执行的 SQL 和查询结果，用简体中文写一段简洁的结论。

要求：
1. 2-4 句话，直接回答用户问题，必须包含关键数字；
2. 如果结果为空，明确说明“没有符合条件的数据”；
3. 不要复述 SQL，不要使用 Markdown 标题。"""


def build_summarize_messages(question: str, sql: str,
                             columns: list[str], rows: list[tuple],
                             row_count: int, truncated: bool,
                             preview_rows: int = 15) -> list[dict]:
    shown = rows[:preview_rows]
    body = "\n".join(str(row) for row in shown) if shown else "（无数据）"
    note = "，已截断" if truncated else ""
    return [
        {"role": "system", "content": SUMMARIZE_SYSTEM},
        {"role": "user", "content": (
            f"问题：{question}\n\n"
            f"执行的 SQL：\n```sql\n{sql}\n```\n\n"
            f"查询结果（共 {row_count} 行{note}，列：{columns}，"
            f"最多展示 {len(shown)} 行）：\n{body}"
        )},
    ]


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
