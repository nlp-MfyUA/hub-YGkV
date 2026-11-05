"""SQL Agent Workflow（LangGraph 版）

以 week13/sql_agent_langchain.py 为基准重写，把原来"函数顺序调用 + while 循环"
换成 LangGraph 的"状态 + 节点 + 条件边"：

    week13/sql_agent_langchain.py          week13/h1/sql_agent_langgraph.py
    -----------------------------------    -----------------------------------------
    run_sql_agent() 里顺序调用函数          StateGraph 的 7 个节点
    for attempt in range(...) 改写循环      validate_sql 的条件边（回环）
    函数间靠参数/局部变量传值                 AgentState 统一承载状态
    ——                                     MemorySaver 检查点（可按 thread_id 恢复）

流程图：

    START
      │
      ▼
    parse_db ──► select_tables ──► generate_sql ──► validate_sql
                                                      │
                            ┌─────────────────────────┼──────────────────────┐
                        通过│                失败且未超限│        失败且超限     │
                            ▼                         ▼                      ▼
                       execute_sql              rewrite_sql               give_up
                            │                         │                      │
                            ▼                         └──► 回到 validate_sql   ▼
                       summarize ─────────────────────────────────────────► END

依赖：
    pip install langgraph          # 其余 langchain-core / langchain-openai 已装

运行：
    export DEEPSEEK_API_KEY=sk-xxxxxxxx
    python3 sql_agent_langgraph.py "数据库里一共有多少位客户？"
    python3 sql_agent_langgraph.py --graph     # 只打印图结构
"""

from typing import Optional, TypedDict, Union
import os
import re
import sys
import traceback
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


# ============================ 0. 配置 ============================

BASE_DIR = Path(__file__).resolve().parent
# 数据库优先用同目录，找不到再用上一级（week13/chinook.db）
DB_FILE = BASE_DIR / "chinook.db"
if not DB_FILE.exists():
    DB_FILE = BASE_DIR.parent / "chinook.db"
DB_URL = f"sqlite:///{DB_FILE}"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"      # 更强的模型可换 deepseek-v4-pro

MAX_REWRITE = 3                        # SQL 改写最大轮数


# ========================= 1. 数据库解析 =========================
class DBParser:
    """DBParser 数据库的解析（与 langchain 版本保持一致）"""

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
        """检查 sql 是否合理（SQLAlchemy 2.0 写法）"""

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
def build_llm(temperature: float = 0.0) -> ChatOpenAI:
    """构建 ChatOpenAI（DeepSeek 走 OpenAI 兼容协议）"""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未设置环境变量 DEEPSEEK_API_KEY")

    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
        timeout=60,
        max_retries=0,  # 重试统一交给 with_retry
    )


_chains: dict = {}


def get_chains() -> dict:
    """惰性构建 LCEL 链（ChatPromptTemplate -> llm -> StrOutputParser）"""
    if _chains:
        return _chains

    def build_chain(prompt: str, temperature: float = 0.0):
        llm = build_llm(temperature).with_retry(
            stop_after_attempt=5,
            wait_exponential_jitter=True,
        )
        return ChatPromptTemplate.from_template(prompt) | llm | StrOutputParser()

    _chains.update(
        {
            "select": build_chain(table_select_prompt),
            "generate": build_chain(answer_prompt),
            "rewrite": build_chain(sql_rewrite_prompt),
            "summarize": build_chain(answer_rewrite_prompt, temperature=0.3),
        }
    )
    return _chains


# =========================== 3. Prompt ===========================
table_select_prompt = """你是一个专业的数据库专家。现在需要你根据用户问题，从下面的表中选择回答问题所必需的、最少的表。
只输出表名，多个表名用英文逗号分隔，不要输出其他内容。

表清单（表名: 字段）：
{table_list}

用户问题：{question}
"""

answer_prompt = """你是一个专业的数据库专家，现在需要你结合表和提问，生成对应的 SQL 语句。请直接输出 SQL，不需要有其他输出，不要使用 markdown 代码块：

数据表样例如下：
{data_sample_mk}

数据表 schema 如下：
{data_schema}

提问：{question}
"""

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
    """数据库解析只做一次，之后复用

    注：parser 持有 SQLAlchemy engine，不适合放进 LangGraph 的 State
    （State 需要可序列化，方便做 checkpoint），所以放在模块级缓存。
    """
    global _parser
    if _parser is None:
        if not DB_FILE.exists():
            raise FileNotFoundError(f"找不到数据库文件：{DB_FILE}")
        _parser = DBParser(DB_URL)
    return _parser


def select_tables(question: str) -> list:
    """挑选相关表"""
    parser = get_parser()
    table_list = "\n".join(
        f"- {name}: {', '.join(parser.get_table_sample(name).columns)}"
        for name in parser.table_names
    )
    raw = get_chains()["select"].invoke(
        {"table_list": table_list, "question": question}
    )

    names = [re.sub(r"[`'\"]", "", x).strip() for x in re.split(r"[,，、\s]+", raw)]
    selected = [x for x in names if x in parser.table_names]

    if not selected:
        print(f"        [warn] 未能解析出表名，回退到全部表。模型输出：{raw[:100]}")
        return list(parser.table_names)
    return selected


def build_context(table_names: list) -> tuple:
    """把选中表的样例和 schema 拼成给模型的上下文"""
    parser = get_parser()
    samples, schemas = [], []
    for name in table_names:
        samples.append(f"### {name}\n{parser.get_table_sample(name).to_markdown()}")
        schemas.append(f"### {name}\n{parser.get_table_fields(name).to_markdown()}")
    return "\n\n".join(samples), "\n\n".join(schemas)


def generate_sql(question: str, data_sample_mk: str, data_schema: str) -> str:
    """生成 SQL"""
    raw = get_chains()["generate"].invoke(
        {
            "data_sample_mk": data_sample_mk,
            "data_schema": data_schema,
            "question": question,
        }
    )
    return clean_sql(raw)


def validate_sql(sql: str) -> tuple:
    """校验 SQL：先挡掉非查询语句，再交给数据库试跑"""
    if not is_read_only(sql):
        return False, "只允许 SELECT / WITH 查询"
    return get_parser().check_sql(sql)


def rewrite_sql(question: str, sql: str, error: str, data_schema: str) -> str:
    """把报错回喂模型，修正 SQL"""
    raw = get_chains()["rewrite"].invoke(
        {
            "data_schema": data_schema,
            "question": question,
            "sql": sql,
            "error": error[-1500:],  # 报错信息太长时只保留尾部
        }
    )
    return clean_sql(raw)


def execute_sql(sql: str) -> list:
    """执行 SQL"""
    return get_parser().execute_sql(sql)


def summarize(question: str, sql: str, rows: list) -> str:
    """结果汇总为自然语言"""
    return get_chains()["summarize"].invoke(
        {
            "question": question,
            "sql": sql,
            "answer": format_rows(rows),
        }
    )


# ========================= 4. 图定义 =========================
class AgentState(TypedDict, total=False):
    """在节点之间流转的共享状态

    total=False：每个节点只返回自己更新的字段，其余保持原值。
    """

    question: str          # 用户问题
    db_tables: list        # 数据库里所有表
    tables: list           # 选中的表
    data_sample: str       # 选中表的样例（markdown）
    data_schema: str       # 选中表的 schema（markdown）
    sql: str               # 当前 SQL
    is_valid: bool         # 校验是否通过
    error: str             # 校验报错
    rewrite_count: int     # 已改写次数
    rows: list             # 执行结果
    answer: str            # 最终自然语言答案


def parse_db_node(state: AgentState) -> dict:
    """[1/7] 数据库解析"""
    parser = get_parser()
    print(f"[1/7] 数据库解析：{len(parser.table_names)} 张表 {parser.table_names}")
    return {"db_tables": list(parser.table_names)}


def select_tables_node(state: AgentState) -> dict:
    """[2/7] table 选择"""
    tables = select_tables(state["question"])
    print(f"[2/7] table 选择：{tables}")
    data_sample, data_schema = build_context(tables)
    return {"tables": tables, "data_sample": data_sample, "data_schema": data_schema}


def generate_sql_node(state: AgentState) -> dict:
    """[3/7] sql 生成"""
    sql = generate_sql(state["question"], state["data_sample"], state["data_schema"])
    print(f"[3/7] sql 生成：\n{sql}")
    return {"sql": sql, "rewrite_count": 0}


def validate_sql_node(state: AgentState) -> dict:
    """[4/7] sql 校验"""
    ok, err = validate_sql(state["sql"])
    attempt = state.get("rewrite_count", 0) + 1
    print(f"[4/7] sql 校验（第 {attempt} 次）：{'通过' if ok else '失败'}")
    return {"is_valid": ok, "error": err}


def rewrite_sql_node(state: AgentState) -> dict:
    """[5/7] sql 改写"""
    print(f"[5/7] sql 改写（错误：{short_error(state['error'])}）")
    sql = rewrite_sql(
        state["question"], state["sql"], state["error"], state["data_schema"]
    )
    print(f"      改写后：\n{sql}")
    return {"sql": sql, "rewrite_count": state.get("rewrite_count", 0) + 1}


def execute_sql_node(state: AgentState) -> dict:
    """[6/7] sql 执行"""
    rows = execute_sql(state["sql"])
    print(f"[6/7] sql 执行：返回 {len(rows)} 行")
    for row in rows[:10]:
        print("      ", row)
    if len(rows) > 10:
        print(f"       ... 共 {len(rows)} 行")
    return {"rows": rows}


def summarize_node(state: AgentState) -> dict:
    """[7/7] 结果汇总"""
    answer = summarize(state["question"], state["sql"], state["rows"])
    print(f"[7/7] 结果汇总：\n{answer}")
    return {"answer": answer}


def give_up_node(state: AgentState) -> dict:
    """改写次数用尽，终止流程"""
    msg = (
        f"SQL 校验失败，已改写 {state.get('rewrite_count', 0)} 次：\n"
        f"{state['sql']}\n{short_error(state['error'])}"
    )
    print(f"[!] {msg}")
    return {"answer": msg}


def route_after_validate(state: AgentState) -> str:
    """条件边：校验通过就执行，否则改写；改写次数用尽则放弃"""
    if state.get("is_valid"):
        return "execute_sql"
    if state.get("rewrite_count", 0) >= MAX_REWRITE:
        return "give_up"
    return "rewrite_sql"


def build_graph():
    """组装并编译状态图"""
    builder = StateGraph(AgentState)

    builder.add_node("parse_db", parse_db_node)
    builder.add_node("select_tables", select_tables_node)
    builder.add_node("generate_sql", generate_sql_node)
    builder.add_node("validate_sql", validate_sql_node)
    builder.add_node("rewrite_sql", rewrite_sql_node)
    builder.add_node("execute_sql", execute_sql_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("give_up", give_up_node)

    builder.add_edge(START, "parse_db")
    builder.add_edge("parse_db", "select_tables")
    builder.add_edge("select_tables", "generate_sql")
    builder.add_edge("generate_sql", "validate_sql")

    # 核心：校验后的条件分支
    builder.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {
            "execute_sql": "execute_sql",
            "rewrite_sql": "rewrite_sql",
            "give_up": "give_up",
        },
    )

    builder.add_edge("rewrite_sql", "validate_sql")   # 改写后回到校验，形成回环
    builder.add_edge("execute_sql", "summarize")
    builder.add_edge("summarize", END)
    builder.add_edge("give_up", END)

    # MemorySaver：把每一步状态存下来，可用 thread_id 恢复/回看
    return builder.compile(checkpointer=MemorySaver())


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ============================ 主流程 ============================
def run_sql_agent(question: str, thread_id: Optional[str] = None) -> dict:
    """用图跑完一整条 SQL Agent 流水线"""
    print(f"\n{'=' * 60}\n用户问题：{question}\n{'=' * 60}")

    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
    result = get_graph().invoke({"question": question}, config=config)

    return {
        "question": question,
        "tables": result.get("tables", []),
        "sql": result.get("sql", ""),
        "rows": result.get("rows", []),
        "answer": result.get("answer", ""),
    }


def print_graph():
    """打印 Mermaid 流程图（可以直接贴到支持 Mermaid 的编辑器里）"""
    print(get_graph().get_graph().draw_mermaid())


def main():
    args = sys.argv[1:]

    if args and args[0] == "--graph":
        print_graph()
        return

    questions = args or [
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
