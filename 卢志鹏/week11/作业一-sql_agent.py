# -*- coding: utf-8 -*-
"""SQL Agent：完整的 Text-to-SQL 工作流

流水线（7 个阶段）：
    1. 数据库解析   DBParser：表/字段统计/外键关系/表样例
    2. table 选择   LLM 结合用户提问，从全部表中选出相关表
    3. sql 生成     LLM 结合所选表 schema + 样例生成 SQL
    4. sql 校验     parser.check_sql 试执行（事务内，只读保护）
    5. sql 改写     校验失败时，LLM 基于原 SQL + 报错信息改写，循环重试
    6. sql 执行     parser.execute_sql 真实执行
    7. 结果汇总     LLM 将 SQL + 查询结果整理为自然语言回答

运行方式：
    python sql_agent.py            # 端到端演示（需 LLM）
    python sql_agent.py selftest   # 仅自测数据库解析/校验/执行（不调 LLM）

依赖：pip install sqlalchemy pandas tabulate openai
"""
import os
import re
import sys
import traceback
from typing import Union

# Windows 控制台中文兼容
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from openai import OpenAI
from sqlalchemy import create_engine, inspect, func, select, Table, MetaData, text

# ============ 配置 ============
# key 优先读环境变量 ZHIPU_API_KEY，便于换 key 不改代码
API_KEY = os.environ.get("ZHIPU_API_KEY", "439786eaa73841239e11e2122d1e2723.xxxxxxxxxxx")
BASE_URL = "https://open.bigmodel.cn/api/paas/v4"  # 智谱 OpenAI 兼容端点
MODEL = "glm-5.3"                                   # 可换 glm-4.5 / glm-4-flash 等

# 数据库文件与脚本同目录，保证在任意 cwd 下都能运行
DB_URL = "sqlite:///" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "chinook.db")

MAX_RETRY = 5        # sql 改写最大重试次数
MAX_RESULT_ROWS = 30 # 结果汇总时最多展示的行数，防刷屏


# ============================================================
# 阶段 1：数据库解析
# ============================================================
class DBParser:
    """DBParser 数据库的解析"""

    def __init__(self, db_url: str) -> None:
        """初始化
        db_url: 数据库链接地址
        mysql:  mysql://root:123456@localhost:3306/mydb?charset=utf8mb4
        sqlite: sqlite:///chinook.db
        """
        # 判断数据库类型
        if "sqlite" in db_url:
            self.db_type = "sqlite"
        elif "mysql" in db_url:
            self.db_type = "mysql"

        # 链接数据库
        self.engine = create_engine(db_url, echo=False)
        self.conn = self.engine.connect()
        self.db_url = db_url

        # 查看表名
        self.inspector = inspect(self.engine)
        self.table_names = self.inspector.get_table_names()  # 获取table信息

        self._table_fields = {}  # 数据表字段
        self.foreign_keys = []   # 数据库外键
        self._table_sample = {}  # 数据表样例

        # 依次对每张表的字段进行统计
        for table_name in self.table_names:
            print("Table ->", table_name)
            self._table_fields[table_name] = {}

            # 累计外键
            self.foreign_keys += [
                {
                    "constrained_table": table_name,
                    "constrained_columns": x["constrained_columns"],
                    "referred_table": x["referred_table"],
                    "referred_columns": x["referred_columns"],
                }
                for x in self.inspector.get_foreign_keys(table_name)
            ]

            # 获取当前表的字段信息
            table_instance = Table(table_name, MetaData(), autoload_with=self.engine)
            table_columns = self.inspector.get_columns(table_name)
            self._table_fields[table_name] = {x["name"]: x for x in table_columns}

            # 对当前字段进行统计
            for column_meta in table_columns:
                # 获取当前字段
                column_instance = getattr(table_instance.columns, column_meta["name"])

                # 统计unique
                query = select(func.count(func.distinct(column_instance)))
                distinct_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]]["distinct"] = distinct_count

                # 统计most frequency value
                field_type = self._table_fields[table_name][column_meta["name"]]["type"]
                field_type = str(field_type)
                if "text" in field_type.lower() or "char" in field_type.lower():
                    query = (
                        select(column_instance, func.count().label("count"))
                        .group_by(column_instance)
                        .order_by(func.count().desc())
                        .limit(1)
                    )
                    top1_value = self.conn.execute(query).fetchone()[0]
                    self._table_fields[table_name][column_meta["name"]]["mode"] = top1_value

                # 统计missing个数
                query = select(func.count()).filter(column_instance == None)
                nan_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]]["nan_count"] = nan_count

                # 统计max
                query = select(func.max(column_instance))
                max_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]]["max"] = max_value

                # 统计min
                query = select(func.min(column_instance))
                min_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]]["min"] = min_value

                # 任意取值
                query = select(column_instance).limit(10)
                random_value = self.conn.execute(query).all()
                random_value = [x[0] for x in random_value]
                random_value = [str(x) for x in random_value if x is not None]
                random_value = list(set(random_value))
                self._table_fields[table_name][column_meta["name"]]["random"] = random_value[:3]

            # 获取表样例（第一行）
            query = select(table_instance)
            self._table_sample[table_name] = pd.DataFrame([self.conn.execute(query).fetchone()])
            self._table_sample[table_name].columns = [x["name"] for x in table_columns]

    def get_table_fields(self, table_name) -> pd.DataFrame:
        """获取表字段信息"""
        return pd.DataFrame.from_dict(self._table_fields[table_name]).T

    def get_data_relations(self) -> pd.DataFrame:
        """获取数据库链接信息（主键和外键）"""
        return pd.DataFrame(self.foreign_keys)

    def get_table_sample(self, table_name) -> pd.DataFrame:
        """获取数据表样例"""
        return self._table_sample[table_name]

    def check_sql(self, sql) -> Union[bool, str]:
        """检查sql是否合理

        参数
            sql: 待执行句子

        返回: 是否可以运行 报错信息
        """
        try:
            with self.engine.begin() as conn:  # begin() 会自动提交和关闭
                conn.execute(text(sql))
            return True, "ok"
        except:
            err_msg = traceback.format_exc()
            return False, err_msg

    def execute_sql(self, sql) -> list:
        """运行SQL"""
        with self.engine.begin() as conn:  # begin() 会自动提交和关闭
            result = conn.execute(text(sql))
        return list(result)


# ============================================================
# 阶段 2~7：SQL Agent
# ============================================================
class SQLAgent:
    """SQL Agent：table选择 -> sql生成 -> sql校验 -> sql改写 -> sql执行 -> 结果汇总"""

    def __init__(self, db_url: str = DB_URL, model: str = MODEL):
        # 数据库解析（阶段1）
        self.parser = DBParser(db_url)

        # LLM 客户端（纯 openai client，兼容智谱等 OpenAI 协议服务）
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        self.model = model
        self.retry_time = MAX_RETRY

        # ===== 各阶段 Prompt =====
        # 阶段2：table 选择
        self._table_select_prompt = """你是一个专业的SQL专家，请分析在给定的表中哪一些表可以用来回答问题。

数据库表之间的外键关系如下：
{#relations#}

用户提问：{#question#}

可选择的表：{#tables#}

请直接输出回答问题所需的表名，多个表用逗号分隔，不要输出其他内容。"""

        # 阶段3：sql 生成
        self._sql_gen_prompt = """你是一个专业的SQL专家，请结合所选表的schema和样例，将用户提问转换为一条可以在SQLite中执行的SQL语句。

用户提问：{#question#}

所选表的schema如下：
{#schema#}

所选表之间的外键关系：
{#relations#}

所选表的数据样例：
{#sample#}

要求：
1. 只能使用上述表中存在的表和字段；
2. 查询类问题使用 SELECT 语句，禁止增删改；
3. 只输出一条SQL，用 ```sql ``` 代码块包裹，不要输出其他内容。"""

        # 阶段5：sql 改写（校验失败后，基于报错修正）
        self._sql_rewrite_prompt = """你是一个专业的SQL专家，此前生成的SQL执行报错，请根据报错信息修正SQL。

用户提问：{#question#}

所选表的schema如下：
{#schema#}

错误的SQL：
```sql
{#sql#}
```

报错信息：
{#error#}

请直接输出修正后的SQL，用 ```sql ``` 代码块包裹，不要输出其他内容。"""

        # 阶段7：结果汇总
        self._summary_prompt = """你是答案汇总专家，请结合用户的提问、执行的SQL和查询结果，用自然语言回答用户的问题。

用户提问：{#question#}

执行SQL：{#sql#}

查询结果：
{#result#}

要求：直接给出结论，不要编造结果中没有的数据。"""

    # ---------- 智能体入口 ----------
    def action(self, question: str) -> str:
        """主流程：问题进，自然语言答案出"""
        print("\n" + "=" * 60)
        print("[用户提问]", question)

        # 阶段2：table 选择
        tables = self.table_select(question)

        # 阶段3：sql 生成
        sql = self.sql_generate(question, tables)

        # 阶段4+5：sql 校验，失败则改写重试
        sql = self.sql_validate_and_rewrite(question, tables, sql)
        if sql is None:
            print("[失败] SQL 校验与改写均未成功")
            return None

        # 阶段6：sql 执行
        rows = self.parser.execute_sql(sql)
        result_str = self.format_rows(rows)
        print("[SQL 执行结果]\n" + result_str)

        # 阶段7：结果汇总
        answer = self.summary(question, sql, result_str)
        print("[最终回答]", answer)
        return answer

    # ---------- 阶段2：table 选择 ----------
    def table_select(self, question: str) -> list:
        """LLM 从全部表中选择回答问题所需的表"""
        relations = self.parser.get_data_relations().to_markdown(index=False)
        prompt = self._table_select_prompt.replace("{#relations#}", relations) \
            .replace("{#question#}", question) \
            .replace("{#tables#}", ", ".join(self.parser.table_names))

        output = self.llm(prompt)
        print("[table 选择-LLM输出]", output)

        # 白名单过滤：LLM 输出中出现的合法表名（防幻觉表名）
        tables = [t for t in self.parser.table_names if re.search(r"\b" + re.escape(t) + r"\b", output)]
        if not tables:  # 一个都没匹配上，兜底用全部表
            print("[table 选择] 未匹配到合法表名，回退为全部表")
            tables = list(self.parser.table_names)
        print("[table 选择]", tables)
        return tables

    # ---------- 阶段3：sql 生成 ----------
    def sql_generate(self, question: str, tables: list) -> str:
        """LLM 结合所选表的 schema + 样例生成 SQL"""
        prompt = self._sql_gen_prompt.replace("{#question#}", question) \
            .replace("{#schema#}", self.build_schema(tables)) \
            .replace("{#relations#}", self.build_relations(tables)) \
            .replace("{#sample#}", self.build_sample(tables))

        sql = self.extract_sql(self.llm(prompt))
        if sql == "":  # 没抽到代码块，提醒一次再生成
            prompt += "\n\n请注意：必须用 ```sql ``` 代码块输出SQL。"
            sql = self.extract_sql(self.llm(prompt))
        print("[SQL 生成]", sql)
        return sql

    # ---------- 阶段4+5：sql 校验 + 改写 ----------
    def sql_validate_and_rewrite(self, question: str, tables: list, sql: str) -> Union[str, None]:
        """check_sql 校验；失败则带着报错信息让 LLM 改写，循环重试"""
        for retry_idx in range(self.retry_time):
            # 阶段4：校验
            ok, err = self.parser.check_sql(sql)
            if ok:
                print("[SQL 校验] 通过 (第%d次尝试)" % (retry_idx + 1))
                return sql

            # 阶段5：改写
            print("[SQL 校验] 失败，进行第%d次改写" % (retry_idx + 1))
            print("[报错信息]\n" + err)
            prompt = self._sql_rewrite_prompt.replace("{#question#}", question) \
                .replace("{#schema#}", self.build_schema(tables)) \
                .replace("{#sql#}", sql) \
                .replace("{#error#}", err)
            sql = self.extract_sql(self.llm(prompt))
            if sql == "":
                print("[SQL 改写] 未抽取到SQL，继续重试")
        # 最后再校验一次改写结果
        ok, err = self.parser.check_sql(sql)
        return sql if ok else None

    # ---------- 阶段7：结果汇总 ----------
    def summary(self, question: str, sql: str, result_str: str) -> str:
        """LLM 将 SQL + 查询结果整理为自然语言回答"""
        prompt = self._summary_prompt.replace("{#question#}", question) \
            .replace("{#sql#}", sql) \
            .replace("{#result#}", result_str)
        return self.llm(prompt)

    # ---------- 工具方法 ----------
    def llm(self, prompt: str) -> str:
        """调用大模型，失败返回空字符串"""
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
            )
            return completion.choices[0].message.content
        except:
            print("[LLM 调用失败]\n" + traceback.format_exc())
            return ""

    @staticmethod
    def extract_sql(text: str) -> str:
        """从 LLM 回答中抽取 SQL（markdown 代码块）"""
        if not text:
            return ""
        # 优先匹配 ```sql ... ```，再退化为任意 ``` ... ```
        for pattern in [r"```sql\n(.*?)```", r"```sql\r\n(.*?)```", r"```\n(.*?)```"]:
            matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            if matches:
                return matches[0].strip()
        # 整段就是 SQL 的情况（select/with 开头）
        stripped = text.strip().strip("`")
        if stripped.lower().startswith(("select", "with")):
            return stripped
        return ""

    def build_schema(self, tables: list) -> str:
        """拼接所选表的字段统计信息（markdown）"""
        parts = []
        for t in tables:
            parts.append("### 表 %s\n%s" % (t, self.parser.get_table_fields(t).to_markdown()))
        return "\n\n".join(parts)

    def build_relations(self, tables: list) -> str:
        """拼接与所选表相关的外键关系"""
        relations = self.parser.get_data_relations()
        mask = relations["constrained_table"].isin(tables) | relations["referred_table"].isin(tables)
        return relations[mask].to_markdown(index=False)

    def build_sample(self, tables: list) -> str:
        """拼接所选表的数据样例"""
        parts = []
        for t in tables:
            parts.append("### 表 %s\n%s" % (t, self.parser.get_table_sample(t).to_markdown(index=False)))
        return "\n\n".join(parts)

    @staticmethod
    def format_rows(rows: list) -> str:
        """把执行结果行格式化为文本，限制行数防刷屏"""
        lines = [" | ".join(str(x) for x in row) for row in rows[:MAX_RESULT_ROWS]]
        if len(rows) > MAX_RESULT_ROWS:
            lines.append("...（共 %d 行，仅展示前 %d 行）" % (len(rows), MAX_RESULT_ROWS))
        return "\n".join(lines) if lines else "（空结果）"


# ============ 入口 ============
def selftest():
    """数据库解析/校验/执行自测（不调 LLM）"""
    print("== 1. 数据库解析 ==")
    print("表数量:", len(parser.table_names))
    print(parser.get_data_relations())
    print(parser.get_table_sample("albums"))
    print(parser.get_table_fields("genres"))

    print("\n== 2. sql 校验（正确/错误各一条）==")
    print(parser.check_sql("SELECT COUNT(DISTINCT ArtistId) FROM albums;"))
    print(parser.check_sql("SELECT COUNT(BadColumn) FROM albums;"))  # 故意报错

    print("\n== 3. sql 执行 ==")
    print(parser.execute_sql("SELECT COUNT(DISTINCT ArtistId) FROM albums;"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        # 自测模式：只验证 DBParser，不调 LLM
        parser = DBParser(DB_URL)
        selftest()
    else:
        # 端到端演示
        agent = SQLAgent()
        questions = [
            "销量最高的前5首曲目名称是什么？",   # 跨表：invoice_items + tracks
            "每个国家的客户数量是多少？",         # 单表：customers
            "总销售额最高的员工叫什么名字？",     # 跨表：invoices + customers + employees
        ]
        for q in questions:
            agent.action(q)
