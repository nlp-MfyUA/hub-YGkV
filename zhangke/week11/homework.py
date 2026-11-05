'''数据库解析'''
from typing import Union
import traceback
from sqlalchemy import create_engine, inspect, func, select, Table, MetaData, text # ORM 框架
import pandas as pd
import os
import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel, function_tool
from typing import Annotated
import re
os.environ['OPENAI_API_KEY'] = 'sk-eea9470395544764b1de22f427cabdff'
os.environ['OPENAI_BASE_URL'] = 'https://api.deepseek.com'

class DBParser:
    '''DBParser 数据库的解析'''
    def __init__(self, db_url:str) -> None:
        '''初始化
        db_url: 数据库链接地址
        mysql: mysql://root:123456@localhost:3306/mydb?charset=utf8mb4
        sqlite: sqlite://chinook.db
        '''

        # 判断数据库类型
        if 'sqlite' in db_url:
            self.db_type = 'sqlite'
        elif 'mysql' in db_url:
            self.db_type = 'mysql'

        # 链接数据库
        self.engine = create_engine(db_url, echo=False)
        self.conn = self.engine.connect()
        self.db_url = db_url

        # 查看表明
        self.inspector = inspect(self.engine)
        self.table_names = self.inspector.get_table_names() # 获取table信息

        self._table_fields = {} # 数据表字段
        self.foreign_keys = [] # 数据库外键
        self._table_sample = {} # 数据表样例

        # 依次对每张表的字段进行统计
        for table_name in self.table_names:
            print("Table ->", table_name)
            self._table_fields[table_name] = {}

            # 累计外键
            self.foreign_keys += [
                {
                    'constrained_table': table_name,
                    'constrained_columns': x['constrained_columns'],
                    'referred_table': x['referred_table'],
                    'referred_columns': x['referred_columns'],
                } for x in self.inspector.get_foreign_keys(table_name)
            ]

            # 获取当前表的字段信息
            table_instance = Table(table_name, MetaData(), autoload_with=self.engine)
            table_columns = self.inspector.get_columns(table_name)
            self._table_fields[table_name] = {x['name']:x for x in table_columns}

            # 对当前字段进行统计
            for column_meta in table_columns:
                # 获取当前字段
                column_instance = getattr(table_instance.columns, column_meta['name'])

                # 统计unique
                query = select(func.count(func.distinct(column_instance)))
                distinct_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['distinct'] = distinct_count

                # 统计most frequency value
                field_type = self._table_fields[table_name][column_meta['name']]['type']
                field_type = str(field_type)
                if 'text' in field_type.lower() or 'char' in field_type.lower():
                    query = (
                        select(column_instance, func.count().label('count'))
                        .group_by(column_instance)
                        .order_by(func.count().desc())
                        .limit(1)
                    )
                    top1_value = self.conn.execute(query).fetchone()[0]
                    self._table_fields[table_name][column_meta['name']]['mode'] = top1_value

                # 统计missing个数
                query = select(func.count()).filter(column_instance == None)
                nan_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['nan_count'] = nan_count

                # 统计max
                query = select(func.max(column_instance))
                max_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['max'] = max_value

                # 统计min
                query = select(func.min(column_instance))
                min_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['min'] = min_value

                # 任意取值
                query = select(column_instance).limit(10)
                random_value = self.conn.execute(query).all()
                random_value = [x[0] for x in random_value]
                random_value = [str(x) for x in random_value if x is not None]
                random_value = list(set(random_value))
                self._table_fields[table_name][column_meta['name']]['random'] = random_value[:3]

            # 获取表样例（第一行）
            query = select(table_instance)
            self._table_sample[table_name] = pd.DataFrame([self.conn.execute(query).fetchone()])
            self._table_sample[table_name].columns = [x['name'] for x in table_columns]

    def get_table_fields(self, table_name) -> pd.DataFrame:
        '''获取表字段信息'''
        return pd.DataFrame.from_dict(self._table_fields[table_name]).T

    def get_data_relations(self) -> pd.DataFrame:
        '''获取数据库链接信息（主键和外键）'''
        return pd.DataFrame(self.foreign_keys)

    def get_table_sample(self, table_name) -> pd.DataFrame:
        '''获取数据表样例'''
        return self._table_sample[table_name]

    def check_sql(self, sql) -> Union[bool, str]:
        '''检查sql是否合理

        参数
            sql: 待执行句子

        返回: 是否可以运行 报错信息
        '''
        try:
            self.execute_sql(sql)
            return True, 'ok'
        except:
            err_msg = traceback.format_exc()
            return False, err_msg

    def execute_sql(self, sql) -> list:
        '''运行SQL'''
        with self.engine.connect() as conn:  # 获取连接
            result = conn.execute(text(sql))  # 用 text() 包装并执行
            return list(result)
parser = DBParser('sqlite:///./chinook.db')

@function_tool
def parse_table(table_name: Annotated[str, "The name of table"]) -> str:
    """return fields of given table"""
    return parser.get_table_fields(table_name).to_markdown()


@function_tool
def list_tables() -> str:
    """列出数据库中所有可用的表名"""
    return "\n".join(parser.table_names)


@function_tool
def get_data_relations() -> str:
    """获取数据库外键关系（用于多表 JOIN）"""
    df = parser.get_data_relations()
    if df.empty:
        return "该数据库没有外键关系"
    return df.to_markdown()


@function_tool
def get_table_sample(table_name: Annotated[str, "The name of table"]) -> str:
    """获取数据表的一行样例数据，用于了解字段取值格式"""
    return parser.get_table_sample(table_name).to_markdown()


@function_tool
def execute_sql_tool(sql: Annotated[str, "要执行的 SQL 语句（仅允许 SELECT）"]) -> str:
    """执行 SELECT 语句并返回结果（最多 50 行）"""
    ok, msg = parser.check_sql(sql)
    if not ok:
        return f"SQL 执行失败：\n{msg}"
    try:
        rows = parser.execute_sql(sql)
        if not rows:
            return "查询成功，但结果为空。"
        # 限制返回行数，防止 token 爆炸
        rows = rows[:50]
        return "\n".join(str(r) for r in rows)
    except Exception:
        return f"SQL 执行异常：\n{traceback.format_exc()}"

class SQLTableSelectAgent:
    """从数据库所有表中挑选出回答问题所需的一张或多张表"""

    def __init__(self):
        self.agent = Agent(
            name="SQL table select agent",
            instructions=(
                "你是一个资深 SQL 专家。用户会提出一个自然语言问题，"
                "并给出一组可选的数据库表名。\n"
                "你的任务：从候选表中选择回答问题所需的表。\n"
                "要求：\n"
                "1. 先调用 list_tables 查看所有表；\n"
                "2. 对可能相关的表调用 parse_table 查看字段，"
                "必要时调用 get_data_relations 判断表间关联；\n"
                "3. 最终只输出被选中表的表名，多个表用英文逗号分隔，"
                "不要输出任何解释性文字。\n"
                "示例输出：Artist,Album"
            ),
            model="deepseek-flash",
            tools=[list_tables, parse_table, get_data_relations],
        )

    async def run(self, question: str) -> str:
        result = await Runner.run(
            self.agent,
            input=(
                f"用户提问如下：{question}\n\n"
                f"可以选择的表格有：{parser.table_names}"
            ),
        )
        # 清理输出，只保留表名
        text = result.final_output.strip()
        return text

class SQLGenerateAgent:
    """根据用户问题和选中的表生成 SQL 语句"""

    def __init__(self):
        self.agent = Agent(
            name="Generate sql agent",
            instructions=(
                "你是一个 SQL 专家。请根据用户提问和给定的相关表，"
                "生成一条可在 {db_type} 数据库上执行的 SQL 语句。\n"
                "规则：\n"
                "1. 只生成 SELECT 查询，不要生成 INSERT/UPDATE/DELETE/DROP 等；\n"
                "2. 严格使用表中真实存在的字段名，可调用 parse_table 确认；\n"
                "3. 如需多表关联，可调用 get_data_relations 查看外键；\n"
                "4. 最终输出格式为：\n"
                "```sql\n<SQL 语句>\n```\n"
                "只输出这一个代码块，不要附加解释。"
            ).format(db_type=parser.db_type),
            model="deepseek-flash",
            tools=[parse_table, get_data_relations, get_table_sample],
        )

    async def run(self, question: str, tables: str) -> str:
        result = await Runner.run(
            self.agent,
            input=(
                f"用户提问：{question}\n"
                f"相关表：{tables}\n"
                f"数据库类型：{parser.db_type}"
            ),
        )
        return self._extract_sql(result.final_output)

    @staticmethod
    def _extract_sql(text: str) -> str:
        """从模型输出中提取 SQL 代码块"""
        m = re.search(r"```sql\s*(.*?)```", text, re.S | re.I)
        if m:
            return m.group(1).strip()
        # 兜底：去掉可能的 markdown 标记
        return text.replace("```", "").strip()


class SQLGenerateAgent:
    """根据用户问题和选中的表生成 SQL 语句"""

    def __init__(self):
        self.agent = Agent(
            name="Generate sql agent",
            instructions=(
                "你是一个 SQL 专家。请根据用户提问和给定的相关表，"
                "生成一条可在 {db_type} 数据库上执行的 SQL 语句。\n"
                "规则：\n"
                "1. 只生成 SELECT 查询，不要生成 INSERT/UPDATE/DELETE/DROP 等；\n"
                "2. 严格使用表中真实存在的字段名，可调用 parse_table 确认；\n"
                "3. 如需多表关联，可调用 get_data_relations 查看外键；\n"
                "4. 最终输出格式为：\n"
                "```sql\n<SQL 语句>\n```\n"
                "只输出这一个代码块，不要附加解释。"
            ).format(db_type=parser.db_type),
            model="deepseek-flash",
            tools=[parse_table, get_data_relations, get_table_sample],
        )

    async def run(self, question: str, tables: str) -> str:
        result = await Runner.run(
            self.agent,
            input=(
                f"用户提问：{question}\n"
                f"相关表：{tables}\n"
                f"数据库类型：{parser.db_type}"
            ),
        )
        return self._extract_sql(result.final_output)

    @staticmethod
    def _extract_sql(text: str) -> str:
        """从模型输出中提取 SQL 代码块"""
        m = re.search(r"```sql\s*(.*?)```", text, re.S | re.I)
        if m:
            return m.group(1).strip()
        # 兜底：去掉可能的 markdown 标记
        return text.replace("```", "").strip()

class SQLCheckAgent:
    """检查 SQL 的语法/语义是否合理，并给出问题诊断"""

    def __init__(self):
        self.agent = Agent(
            name="SQL check agent",
            instructions=(
                "你是一个 SQL 语法与语义校验专家。你会收到一条 SQL 语句"
                "以及其涉及的表结构信息。\n"
                "请完成以下检查：\n"
                "1. 语法是否正确（对应数据库方言：{db_type}）；\n"
                "2. 字段名、表名是否真实存在；\n"
                "3. 是否为只读 SELECT（如含写操作请指出）；\n"
                "4. 是否存在明显语义错误（如聚合未分组、JOIN 条件缺失等）。\n"
                "最终输出格式：\n"
                "第一行：PASS 或 FAIL\n"
                "后续行（FAIL 时）：具体问题描述，每条一行。\n"
                "不要输出其它内容。"
            ).format(db_type=parser.db_type),
            model="deepseek-flash",
            tools=[parse_table, get_data_relations],
        )

    async def run(self, sql: str, tables: str) -> tuple[bool, str]:
        # 先做本地快速校验（真实执行一次）
        ok, msg = parser.check_sql(sql)
        if not ok:
            # 本地执行失败，直接把错误信息交给 Agent 分析
            local_hint = f"本地执行报错：\n{msg}"
        else:
            local_hint = "本地执行通过。"

        result = await Runner.run(
            self.agent,
            input=(
                f"待校验 SQL：\n{sql}\n\n"
                f"涉及表：{tables}\n"
                f"表结构请调用 parse_table 获取。\n"
                f"本地预检结果：{local_hint}"
            ),
        )
        text = result.final_output.strip()
        passed = text.upper().startswith("PASS")
        return passed, text

class SQLRewriteAgent:
    """当校验失败时，根据错误信息改写 SQL"""

    def __init__(self):
        self.agent = Agent(
            name="SQL rewrite agent",
            instructions=(
                "你是一个 SQL 修复专家。用户会给你：原始 SQL、校验失败原因、"
                "以及相关表结构。请修复 SQL 使其能够正确执行。\n"
                "规则：\n"
                "1. 保持用户查询意图不变；\n"
                "2. 严格使用真实存在的表名与字段名（可调用 parse_table 确认）；\n"
                "3. 只输出修复后的 SQL 代码块：\n"
                "```sql\n<SQL>\n```\n"
                "不要解释。"
            ),
            model="deepseek-flash",
            tools=[parse_table, get_data_relations],
        )

    async def run(self, question: str, sql: str, error_msg: str, tables: str) -> str:
        result = await Runner.run(
            self.agent,
            input=(
                f"用户原始问题：{question}\n"
                f"原始 SQL：\n{sql}\n\n"
                f"校验失败原因：\n{error_msg}\n\n"
                f"涉及表：{tables}\n"
                f"数据库类型：{parser.db_type}"
            ),
        )
        return SQLGenerateAgent._extract_sql(result.final_output)

class SQLExecuteAgent:
    """执行 SQL 并对结果进行自然语言总结"""

    def __init__(self):
        self.agent = Agent(
            name="SQL execute agent",
            instructions=(
                "你是一个数据分析助手。你会收到用户的原始问题、执行的 SQL、"
                "以及查询返回的原始结果。\n"
                "请用自然、简洁的中文回答用户问题。\n"
                "如果结果为空，请说明未查询到数据；"
                "如果结果较多，请给出关键结论与必要的数据展示。"
            ),
            model="deepseek-flash",
            tools=[execute_sql_tool],
        )

    async def run(self, question: str, sql: str) -> str:
        # 直接执行，把结果交给 Agent 总结
        ok, msg = parser.check_sql(sql)
        if not ok:
            return f"SQL 执行失败：\n{msg}"

        rows = parser.execute_sql(sql)[:50]
        result_text = "\n".join(str(r) for r in rows) if rows else "（空结果）"

        result = await Runner.run(
            self.agent,
            input=(
                f"用户问题：{question}\n\n"
                f"执行 SQL：\n{sql}\n\n"
                f"查询结果（最多 50 行）：\n{result_text}"
            ),
        )
        return result.final_output

class SQLWorkflow:
    """串联 表选择 → SQL生成 → 校验 → (改写) → 执行 的完整流程"""

    def __init__(self, max_rewrite: int = 2):
        self.table_agent = SQLTableSelectAgent()
        self.generate_agent = SQLGenerateAgent()
        self.check_agent = SQLCheckAgent()
        self.rewrite_agent = SQLRewriteAgent()
        self.execute_agent = SQLExecuteAgent()
        self.max_rewrite = max_rewrite

    async def run(self, question: str, verbose: bool = True):
        trace = {}

        # Step 1: 选表
        tables = await self.table_agent.run(question)
        trace["tables"] = tables
        if verbose:
            print(f"[1] 选表结果: {tables}")

        # Step 2: 生成 SQL
        sql = await self.generate_agent.run(question, tables)
        trace["sql"] = sql
        if verbose:
            print(f"[2] 生成 SQL:\n{sql}")

        # Step 3 & 4: 校验 + 改写（循环）
        for i in range(self.max_rewrite + 1):
            passed, check_msg = await self.check_agent.run(sql, tables)
            trace[f"check_{i}"] = check_msg
            if verbose:
                print(f"[3.{i}] 校验结果: {check_msg}")

            if passed:
                break
            if i == self.max_rewrite:
                return {
                    "success": False,
                    "error": "多次改写后仍未通过校验",
                    "trace": trace,
                }

            # Step 4: 改写
            sql = await self.rewrite_agent.run(question, sql, check_msg, tables)
            trace[f"rewrite_{i}"] = sql
            if verbose:
                print(f"[4.{i}] 改写后 SQL:\n{sql}")

        # Step 5: 执行 + 总结
        answer = await self.execute_agent.run(question, sql)
        trace["answer"] = answer
        if verbose:
            print(f"[5] 最终回答:\n{answer}")

        return {
            "success": True,
            "tables": tables,
            "sql": sql,
            "answer": answer,
            "trace": trace,
        }


# ============ 使用示例 ============
async def main():
    workflow = SQLWorkflow(max_rewrite=2)
    result = await workflow.run("查询销量最高的前 5 位艺术家及其专辑数量")
    print("\n===== 最终结果 =====")
    print("SQL:", result["sql"])
    print("答案:", result["answer"])


if __name__ == "__main__":
    asyncio.run(main())