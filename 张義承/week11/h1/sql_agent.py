"""SQL Agent Workflow（单文件版）

仿照 ai/review/week11/04_SQL-Code-Agent-Demo/sql-agent.ipynb，把 notebook 里
分散的逻辑串成一条完整的 SQL Agent 流水线：

    [1/7] 数据库解析    DBParser       —— 同 notebook 的 DBParser / chinook_parser.py
    [2/7] table 选择    select_tables  —— 新增：先从全部表里挑出相关表
    [3/7] sql 生成      generate_sql   —— 同 notebook 的 answer_prompt
    [4/7] sql 校验      validate_sql   —— 同 notebook 的 parser.check_sql
    [5/7] sql 改写      rewrite_sql    —— 新增：把报错信息回喂模型修正
    [6/7] sql 执行      execute_sql    —— 同 notebook 的 parser.execute_sql
    [7/7] 结果汇总      summarize      —— 同 notebook 的 answer_rewrite_prompt

相对 notebook 只做了 2 处必要修改，方便逐段对照：
    1. 模型调用：GLM(JWT 鉴权) -> DeepSeek(Bearer 鉴权)，密钥读环境变量 DEEPSEEK_API_KEY
    2. engine.execute() -> SQLAlchemy 2.0 的 conn.execute(text(...))

依赖：sqlalchemy、pandas、requests、tabulate（DataFrame.to_markdown 需要）

运行：
    export DEEPSEEK_API_KEY=sk-xxxxxxxx
    python3 sql_agent.py "数据库里一共有多少位客户？"
"""

from typing import Optional, Union
import os
import re
import sys
import time
import traceback
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text


# ============================ 0. 配置 ============================

BASE_DIR = Path(__file__).resolve().parent
DB_URL = f"sqlite:///{BASE_DIR / 'chinook.db'}"  # 用绝对路径，避免依赖执行目录

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"      # 更强的模型可换 deepseek-v4-pro

MAX_REWRITE = 3                     # SQL 改写最大轮数


# ========================= 1. 数据库解析 =========================
class DBParser:
    """DBParser 数据库的解析（与 notebook 保持一致）"""

    def __init__(self, db_url: str) -> None:
        """初始化
        db_url: 数据库链接地址
        mysql: mysql://root:123456@localhost:3306/mydb?charset=utf8mb4
        sqlite: sqlite://chinook.db
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
        self.table_names = self.inspector.get_table_names()  # 获取 table 信息

        self._table_fields = {}  # 数据表字段
        self.foreign_keys = []  # 数据库外键
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

                # 统计 unique
                query = select(func.count(func.distinct(column_instance)))
                distinct_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]][
                    "distinct"
                ] = distinct_count

                # 统计 most frequency value
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
                    self._table_fields[table_name][column_meta["name"]][
                        "mode"
                    ] = top1_value

                # 统计 missing 个数
                query = select(func.count()).filter(column_instance == None)
                nan_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]][
                    "nan_count"
                ] = nan_count

                # 统计 max
                query = select(func.max(column_instance))
                max_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]]["max"] = max_value

                # 统计 min
                query = select(func.min(column_instance))
                min_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta["name"]]["min"] = min_value

                # 任意取值
                query = select(column_instance).limit(10)
                random_value = self.conn.execute(query).all()
                random_value = [x[0] for x in random_value]
                random_value = [str(x) for x in random_value if x is not None]
                random_value = list(set(random_value))
                self._table_fields[table_name][column_meta["name"]]["random"] = (
                    random_value[:3]
                )

            # 获取表样例（第一行）
            query = select(table_instance)
            self._table_sample[table_name] = pd.DataFrame(
                [self.conn.execute(query).fetchone()]
            )
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
        """检查 sql 是否合理

        参数
            sql: 待执行句子

        返回: 是否可以运行 报错信息

        注：notebook 里用的是 self.engine.execute(sql)，
        SQLAlchemy 2.0 已移除该方法，这里换成 Connection.execute(text(...))
        """

        try:
            with self.engine.connect() as conn:
                conn.execute(text(sql))  # with 块退出未 commit，会自动回滚
            return True, "ok"
        except Exception:
            err_msg = traceback.format_exc()
            return False, err_msg

    def execute_sql(self, sql) -> list:
        """运行 SQL"""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql))
            return [tuple(row) for row in result]


# ========================= 2. 模型调用 =========================
def ask_llm(question: str, temperature: float = 0.3, nretry: int = 5) -> Optional[dict]:
    """调用 DeepSeek（OpenAI 兼容协议）

    替代 notebook 里的 generate_token + GLM 调用：
    DeepSeek 直接用 Bearer 鉴权，不需要 JWT；也没有 GLM 的 "p" 参数。
    返回值结构与原来一致，仍可用 ['choices'][0]['message']['content'] 取值。
    """
    if nretry == 0:
        return None

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未设置环境变量 DEEPSEEK_API_KEY")

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    data = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": question}],
        "temperature": temperature,
        "stream": False,
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code == 200:
            return response.json()
        print(f"[HTTP {response.status_code}] {response.text[:200]}")
    except requests.RequestException as e:
        print("request error:", e)

    time.sleep(2 ** (5 - nretry))  # 退避重试：1s -> 2s -> 4s -> 8s -> 16s
    return ask_llm(question, temperature, nretry - 1)


def ask_text(prompt: str, temperature: float = 0.3) -> str:
    """ask_llm 的薄封装：直接拿文本结果"""
    resp = ask_llm(prompt, temperature=temperature)
    if not resp:
        raise RuntimeError("模型调用失败（重试已耗尽）")
    return resp["choices"][0]["message"]["content"].strip()


# =========================== 3. Prompt ===========================
# table 选择（notebook 里没有，新增的第一步）
table_select_prompt = """你是一个专业的数据库专家。现在需要你根据用户问题，从下面的表中选择回答问题所必需的、最少的表。
只输出表名，多个表名用英文逗号分隔，不要输出其他内容。

表清单（表名: 字段）：
{table_list}

用户问题：{question}
"""

# sql 生成（对应 notebook 的 answer_prompt）
answer_prompt = """你是一个专业的数据库专家，现在需要你结合表和提问，生成对应的 SQL 语句。请直接输出 SQL，不需要有其他输出，不要使用 markdown 代码块：

数据表样例如下：
{data_sample_mk}

数据表 schema 如下：
{data_schema}

提问：{question}
"""

# sql 改写（notebook 里没有，新增：校验失败后回喂报错）
sql_rewrite_prompt = """你是一个专业的数据库专家。下面的 SQL 在数据库中执行报错了，请结合错误信息和表结构修正它。
只输出修正后的 SQL，不要输出其他内容，不要使用 markdown 代码块。

数据表 schema 如下：
{data_schema}

用户问题：{question}

原始 SQL：
{sql}

错误信息：
{error}
"""

# 结果汇总（对应 notebook 的 answer_rewrite_prompt）
answer_rewrite_prompt = """你是一个专业的数据库专家，将下面的问题回答组织为自然语言。：

原始问题：{question}

执行 SQL：{sql}

原始结果：{answer}
"""


# ========================== 工具函数 ==========================
def clean_sql(raw_sql: str) -> str:
    """去掉模型可能带上的 markdown 代码块"""
    sql = raw_sql.strip()
    sql = re.sub(r"^```[a-zA-Z]*\s*", "", sql)   # 开头的 ```sql
    sql = re.sub(r"\s*```$", "", sql)            # 结尾的 ```
    return sql.strip()


def is_read_only(sql: str) -> bool:
    """只放行查询语句，避免模型生成 DROP / DELETE 之类"""
    head = sql.lstrip().lower()
    return head.startswith("select") or head.startswith("with")


def short_error(err: str) -> str:
    """从 traceback 里挑出真正有用的那行报错"""
    for line in err.strip().splitlines():
        if "Error" in line:
            return line.strip()
    return err.strip().splitlines()[0] if err.strip() else ""


def format_rows(rows: list, limit: int = 50) -> str:
    """把执行结果压成一段文本，限制长度避免 prompt 过长"""
    if not rows:
        return "（无结果）"
    body = "\n".join(str(r) for r in rows[:limit])
    if len(rows) > limit:
        body += f"\n... 共 {len(rows)} 行，仅展示前 {limit} 行"
    return body


# ========================== 各阶段实现 ==========================
_parser: Optional[DBParser] = None


def get_parser() -> DBParser:
    """数据库解析只做一次，之后复用"""
    global _parser
    if _parser is None:
        db_file = BASE_DIR / "chinook.db"
        if not db_file.exists():
            raise FileNotFoundError(f"找不到数据库文件：{db_file}")
        _parser = DBParser(DB_URL)
    return _parser


def select_tables(parser: DBParser, question: str) -> list:
    """[2/7] table 选择：先从全部表里挑出相关表"""
    table_list = "\n".join(
        f"- {name}: {', '.join(parser.get_table_sample(name).columns)}"
        for name in parser.table_names
    )
    prompt = table_select_prompt.format(table_list=table_list, question=question)
    raw = ask_text(prompt, temperature=0)

    names = [re.sub(r"[`'\"]", "", x).strip() for x in re.split(r"[,，、\s]+", raw)]
    selected = [x for x in names if x in parser.table_names]

    if not selected:
        print(f"        [warn] 未能解析出表名，回退到全部表。模型输出：{raw[:100]}")
        return list(parser.table_names)
    return selected


def build_context(parser: DBParser, table_names: list) -> tuple:
    """把选中表的样例和 schema 拼成给模型的上下文"""
    samples, schemas = [], []
    for name in table_names:
        samples.append(f"### {name}\n{parser.get_table_sample(name).to_markdown()}")
        schemas.append(f"### {name}\n{parser.get_table_fields(name).to_markdown()}")
    return "\n\n".join(samples), "\n\n".join(schemas)


def generate_sql(question: str, data_sample_mk: str, data_schema: str) -> str:
    """[3/7] sql 生成"""
    prompt = answer_prompt.format(
        data_sample_mk=data_sample_mk,
        data_schema=data_schema,
        question=question,
    )
    return clean_sql(ask_text(prompt, temperature=0))


def validate_sql(parser: DBParser, sql: str) -> tuple:
    """[4/7] sql 校验：先挡掉非查询语句，再交给数据库试跑"""
    if not is_read_only(sql):
        return False, "只允许 SELECT / WITH 查询"
    return parser.check_sql(sql)


def rewrite_sql(question: str, sql: str, error: str, data_schema: str) -> str:
    """[5/7] sql 改写：把报错回喂模型"""
    prompt = sql_rewrite_prompt.format(
        data_schema=data_schema,
        question=question,
        sql=sql,
        error=error[-1500:],  # 报错信息太长时只保留尾部
    )
    return clean_sql(ask_text(prompt, temperature=0))


def execute_sql(parser: DBParser, sql: str) -> list:
    """[6/7] sql 执行"""
    return parser.execute_sql(sql)


def summarize(question: str, sql: str, rows: list) -> str:
    """[7/7] 结果汇总"""
    prompt = answer_rewrite_prompt.format(
        question=question,
        sql=sql,
        answer=format_rows(rows),
    )
    return ask_text(prompt, temperature=0.3)


# ============================ 主流程 ============================
def run_sql_agent(question: str, parser: Optional[DBParser] = None,
                  max_rewrite: int = MAX_REWRITE) -> dict:
    """跑完一整条 SQL Agent 流水线"""
    parser = parser or get_parser()

    print(f"\n{'=' * 60}\n用户问题：{question}\n{'=' * 60}")

    # [1/7] 数据库解析
    print(f"[1/7] 数据库解析：{len(parser.table_names)} 张表 {parser.table_names}")

    # [2/7] table 选择
    tables = select_tables(parser, question)
    print(f"[2/7] table 选择：{tables}")

    data_sample_mk, data_schema = build_context(parser, tables)

    # [3/7] sql 生成
    sql = generate_sql(question, data_sample_mk, data_schema)
    print(f"[3/7] sql 生成：\n{sql}")

    # [4/7] sql 校验 + [5/7] sql 改写
    for attempt in range(max_rewrite + 1):
        ok, err = validate_sql(parser, sql)
        print(f"[4/7] sql 校验（第 {attempt + 1} 次）：{'通过' if ok else '失败'}")
        if ok:
            break
        if attempt == max_rewrite:
            raise RuntimeError(f"SQL 校验失败，已改写 {max_rewrite} 次：\n{sql}\n{err}")

        print(f"[5/7] sql 改写（错误：{short_error(err)}）")
        sql = rewrite_sql(question, sql, err, data_schema)
        print(f"      改写后：\n{sql}")

    # [6/7] sql 执行
    rows = execute_sql(parser, sql)
    print(f"[6/7] sql 执行：返回 {len(rows)} 行")
    for row in rows[:10]:
        print("      ", row)
    if len(rows) > 10:
        print(f"       ... 共 {len(rows)} 行")

    # [7/7] 结果汇总
    answer = summarize(question, sql, rows)
    print(f"[7/7] 结果汇总：\n{answer}")

    return {
        "question": question,
        "tables": tables,
        "sql": sql,
        "rows": rows,
        "answer": answer,
    }


def main():
    questions = sys.argv[1:] or [
        "数据库里一共有多少位客户？",
        "哪个流派（genre）的歌曲数量最多，有多少首？",
        "每位员工分别负责多少位客户？",
    ]
    for question in questions:
        try:
            run_sql_agent(question)
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
