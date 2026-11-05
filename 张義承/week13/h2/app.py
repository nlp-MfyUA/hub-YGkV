"""Chinook SQL Agent —— Web 前端后端（FastAPI）

直接复用 week13/h1/sql_agent_langgraph.py 的 LangGraph 实现：
浏览器输入自然语言 → 跑图 → 返回自然语言答案 + SQL + 执行结果。

运行：
    cd week13/h2
    export DEEPSEEK_API_KEY=sk-xxxxxxxx
    python3 -m uvicorn app:app --reload --port 8000
    浏览器打开 http://127.0.0.1:8000
"""

import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text

# ------------------------------------------------------------------
# 配置：必须先加载 .env，再导入 h1 模块
#
# h1 在 import 时就把 DEEPSEEK_API_KEY 读进了模块常量，如果先 import
# 再 load_dotenv，模块里拿到的仍然是空字符串。
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# 复用 h1 的 LangGraph 实现（h1 不是包，这里把目录加进 sys.path）
H1_DIR = (BASE_DIR.parent / "h1").resolve()
sys.path.insert(0, str(H1_DIR))

import sql_agent_langgraph as agent  # noqa: E402

STATIC_DIR = BASE_DIR / "static"

MAX_ROWS = 200      # 单次返回给前端的最大行数


# ------------------------------------------------------------------
# 给前端用的提示信息：用户能问什么
# ------------------------------------------------------------------
CAPABILITIES = [
    {
        "icon": "👥",
        "title": "客户与地区",
        "desc": "客户总数、各国客户分布、消费金额排行、支持员工分配",
    },
    {
        "icon": "🧾",
        "title": "销售与发票",
        "desc": "发票数量、销售总额、客单价、按年份/国家的趋势",
    },
    {
        "icon": "🎵",
        "title": "音乐内容",
        "desc": "歌手、专辑、歌曲数量、流派分布、播放列表收录",
    },
    {
        "icon": "🧑‍💼",
        "title": "员工与支持",
        "desc": "每位员工负责的客户数、上下级汇报关系",
    },
]

EXAMPLES = [
    "数据库里一共有多少位客户？",
    "哪个国家的客户数量最多？",
    "销售额最高的前 5 个国家是哪些？",
    "平均每张发票的金额是多少？",
    "哪个流派的歌曲数量最多？",
    "哪位艺术家的专辑数量最多？",
    "每位员工分别负责多少位客户？",
    "哪一年的开票金额最高？",
]

WELCOME = (
    "你好！我可以把自然语言问题翻译成 SQL，在 Chinook 音乐商店数据库上执行，"
    "再用中文总结结果。\n\n"
    "你可以问客户、销售、音乐内容、员工相关的问题——左侧列了一些示例，"
    "直接点击就能试。"
)


# ------------------------------------------------------------------
# 应用
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预热数据库解析和模型客户端，避免首个请求卡顿"""
    if not agent.DEEPSEEK_API_KEY:
        print(
            "[warn] 未检测到 DEEPSEEK_API_KEY："
            "请在 h2/.env 中写入，或在启动前 export"
        )
    try:
        agent.get_parser()
    except Exception as e:  # 数据库问题不阻止服务启动，查询时再报
        print(f"[warn] 数据库预加载失败：{e}")
    try:
        agent.get_chains()
    except Exception as e:
        print(f"[warn] 模型初始化失败：{e}")
    yield


app = FastAPI(title="Chinook SQL Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class QueryRequest(BaseModel):
    question: str
    thread_id: str | None = None


def _safe(value):
    """把数据库返回值转成 JSON 可序列化的类型"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _columns_and_rows(sql: str):
    """重新执行一次 SQL，拿到列名

    h1 的 execute_sql 只返回 tuple，不带列名；Chinook 数据量很小，
    多执行一次的成本可以忽略，换来前端能渲染带表头的结果表。
    """
    engine = agent.get_parser().engine
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = [str(c) for c in result.keys()]
        rows = [[_safe(v) for v in row] for row in result]
    return columns, rows


def _run_graph(question: str, thread_id: str) -> dict:
    """跑一遍 LangGraph，返回结构化结果"""
    config = {"configurable": {"thread_id": thread_id}}
    graph = agent.get_graph()

    steps = []
    try:
        # stream_mode="updates"：每完成一个节点就产出一条 {节点名: 状态更新}
        for chunk in graph.stream(
            {"question": question}, config=config, stream_mode="updates"
        ):
            steps.extend(chunk.keys())
    except Exception as e:
        return {
            "ok": False,
            "error": f"执行失败：{e}",
            "steps": steps,
            "thread_id": thread_id,
        }

    values = graph.get_state(config).values
    sql = values.get("sql", "")
    answer = values.get("answer", "")

    columns, rows = [], []
    if sql and values.get("is_valid"):
        try:
            columns, rows = _columns_and_rows(sql)
        except Exception as e:
            print(f"[warn] 取列名失败：{e}")
            rows = [list(r) for r in values.get("rows", [])]

    return {
        "ok": True,
        "thread_id": thread_id,
        "answer": answer,
        "sql": sql,
        "tables": values.get("tables", []),
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "row_count": len(rows),
        "truncated": len(rows) > MAX_ROWS,
        "steps": steps,
        "gave_up": answer.startswith("SQL 校验失败"),
    }


# ------------------------------------------------------------------
# 路由
# ------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/meta")
def meta():
    """前端启动时拉取：能力提示、示例问题、欢迎语"""
    return {
        "capabilities": CAPABILITIES,
        "examples": EXAMPLES,
        "welcome": WELCOME,
        "model": agent.DEEPSEEK_MODEL,
    }


@app.post("/api/query")
def query(req: QueryRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    if not agent.DEEPSEEK_API_KEY:
        return {
            "ok": False,
            "error": "服务端未配置 DEEPSEEK_API_KEY：请在 h2/.env 中写入，或在启动前 export。",
            "steps": [],
            "thread_id": "",
        }

    # 每次提问用独立 thread_id，避免上一轮状态串到这一轮
    thread_id = req.thread_id or f"web-{uuid.uuid4().hex[:12]}"
    return _run_graph(question, thread_id)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "db": str(agent.DB_FILE),
        "model": agent.DEEPSEEK_MODEL,
        "api_key_set": bool(agent.DEEPSEEK_API_KEY),
    }
