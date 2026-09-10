"""FastAPI 路由：认证 / 模型管理 / 研究任务 / SSE + 静态前端。"""
import json
import queue

import auth
import db
import keyciphers
import llm
import pipeline
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

app = FastAPI(title="深度研究助手")
BASE_DIR = Path(__file__).parent


# ---------- 认证 ----------

class LoginBody(BaseModel):
    username: str
    password: str


def _user_from_token(token: str) -> dict:
    payload = auth.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="未登录或 token 无效")
    user = db.query_one("SELECT id, username FROM users WHERE id = ?", (payload["uid"],))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def _auth_from_query(token: str = Query(default="")) -> dict:
    """前端除 SSE 外的请求统一走 ?token= 查询参数（EventSource 不能带 header，普通 fetch 也不麻烦）。"""
    if not token:
        raise HTTPException(status_code=401, detail="缺少 token 查询参数")
    return _user_from_token(token)


@app.post("/api/login")
def login(body: LoginBody):
    user = auth.get_user(body.username)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth.issue_token(user["id"], user["username"])
    return {"token": token, "user": {"id": user["id"], "username": user["username"]}}


@app.get("/api/me")
def me(user: dict = Depends(_auth_from_query)):
    return user


# ---------- 模型管理 ----------

class ModelBody(BaseModel):
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    is_default: bool = False


def _public_model(m: dict) -> dict:
    m = dict(m)
    m["api_key_masked"] = keyciphers.mask(keyciphers.decrypt(m.pop("api_key_enc")))
    m.pop("user_id", None)
    return m


@app.get("/api/models")
def list_models(user: dict = Depends(_auth_from_query)):
    rows = db.query("SELECT * FROM models WHERE user_id = ? ORDER BY is_default DESC, id", (user["id"],))
    return [_public_model(m) for m in rows]


@app.post("/api/models")
def add_model(body: ModelBody, user: dict = Depends(_auth_from_query)):
    if body.is_default:
        db.execute("UPDATE models SET is_default=0 WHERE user_id=?", (user["id"],))
    new_id = db.execute(
        "INSERT INTO models (user_id, name, base_url, model_name, api_key_enc, is_default) VALUES (?, ?, ?, ?, ?, ?)",
        (user["id"], body.name, body.base_url, body.model_name,
         keyciphers.encrypt(body.api_key), 1 if body.is_default else 0),
    )
    row = db.query_one("SELECT * FROM models WHERE id = ?", (new_id,))
    ok = llm.health_check(row, new_id)  # 添加时"测试连接"
    return {"id": new_id, "health": "ok" if ok else "fail"}


@app.delete("/api/models/{model_id}")
def del_model(model_id: int, user: dict = Depends(_auth_from_query)):
    row = db.query_one("SELECT * FROM models WHERE id = ? AND user_id = ?", (model_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="模型不存在")
    # 历史任务仍保留记录，但不再关联已删除的模型
    db.execute("UPDATE tasks SET model_id=NULL WHERE model_id=?", (model_id,))
    db.execute("DELETE FROM models WHERE id = ?", (model_id,))
    return {"ok": True}


@app.post("/api/models/{model_id}/health")
def recheck_health(model_id: int, user: dict = Depends(_auth_from_query)):
    row = db.query_one("SELECT * FROM models WHERE id = ? AND user_id = ?", (model_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="模型不存在")
    ok = llm.health_check(row, model_id)  # 手动重检
    return {"health": "ok" if ok else "fail"}


@app.post("/api/models/{model_id}/default")
def set_default(model_id: int, user: dict = Depends(_auth_from_query)):
    db.execute("UPDATE models SET is_default=0 WHERE user_id=?", (user["id"],))
    db.execute("UPDATE models SET is_default=1 WHERE id=? AND user_id=?", (model_id, user["id"]))
    return {"ok": True}


# ---------- 研究任务 ----------

class TaskBody(BaseModel):
    topic: str = Field(min_length=1)
    model_id: int
    max_rounds: int = Field(default=3, ge=1, le=10)


@app.post("/api/tasks")
def create_task(body: TaskBody, user: dict = Depends(_auth_from_query)):
    models = db.query("SELECT id FROM models WHERE user_id = ?", (user["id"],))
    if not models:
        # 没有任何模型时：直接报错引导去模型页，没有服务端兜底模型
        raise HTTPException(status_code=400, detail="还没有配置模型，请先到「模型管理」添加 OpenAI 兼容模型")
    m = db.query_one("SELECT id FROM models WHERE id = ? AND user_id = ?", (body.model_id, user["id"]))
    if not m:
        raise HTTPException(status_code=400, detail="模型不存在或不属于当前用户")
    task_id = db.execute(
        "INSERT INTO tasks (user_id, topic, model_id, max_rounds) VALUES (?, ?, ?, ?)",
        (user["id"], body.topic, body.model_id, body.max_rounds),
    )
    pipeline.start(task_id)
    return {"task_id": task_id}


@app.get("/api/tasks")
def list_tasks(
    user: dict = Depends(_auth_from_query),
    keyword: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    where = ["t.user_id = ?"]
    args = [user["id"]]
    if keyword:
        where.append("t.topic LIKE ?")
        args.append(f"%{keyword}%")
    if date_from:
        where.append("date(t.created_at) >= ?")
        args.append(date_from)
    if date_to:
        where.append("date(t.created_at) <= ?")
        args.append(date_to)
    total = db.query_one(
        f"SELECT COUNT(*) AS n FROM tasks t WHERE {' AND '.join(where)}", args,
    )["n"]
    rows = db.query(
        f"""SELECT t.*, m.name AS model_label FROM tasks t
            LEFT JOIN models m ON m.id = t.model_id
            WHERE {' AND '.join(where)}
            ORDER BY t.id DESC LIMIT ? OFFSET ?""",
        (*args, page_size, (page - 1) * page_size),
    )
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _require_task_owner(task_id: int, user: dict) -> dict:
    t = db.query_one("SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user["id"]))
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, user: dict = Depends(_auth_from_query)):
    t = _require_task_owner(task_id, user)
    r = db.query_one("SELECT report_md, sources, meta, created_at FROM reports WHERE task_id = ?", (task_id,))
    out = dict(t)
    if r:
        out["report"] = {
            "report_md": r["report_md"],
            "sources": json.loads(r["sources"] or "[]"),
            "meta": json.loads(r["meta"] or "{}"),
            "created_at": r["created_at"],
        }
    return out


# ---------- 报告导出 ----------

def _report_file(task_id: int, user: dict):
    _require_task_owner(task_id, user)
    r = db.query_one("SELECT report_md FROM reports WHERE task_id = ?", (task_id,))
    if not r:
        raise HTTPException(status_code=400, detail="该任务还没有生成报告")
    return r["report_md"]


@app.get("/api/tasks/{task_id}/export")
def export_task(
    task_id: int,
    user: dict = Depends(_auth_from_query),
    fmt: str = Query(default="markdown", pattern="^(markdown|pdf)$"),
):
    """导出报告：markdown 下载 .md；pdf 由前端渲染后打印（此端点统一返回 markdown，
    前端据此弹窗打印另存为 PDF，避免服务端引 headless 浏览器依赖）。"""
    _report_file(task_id, user)
    t = db.query_one("SELECT topic FROM tasks WHERE id = ?", (task_id,))
    filename = f"research-report-{task_id}.{'md' if fmt == 'markdown' else 'pdf'}"
    from fastapi.responses import Response
    return Response(
        content=_report_file(task_id, user),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------- SSE ----------

def sse_stream(task_id: int, last_event_id: str):
    q: "queue.Queue" = queue.Queue()
    subs = pipeline.SUBSCRIBERS
    subs.setdefault(task_id, []).append(q)
    try:
        last_sent = int(last_event_id or 0)
        # 断线重连：按 Last-Event-ID 补发已落库事件
        rows = db.query(
            "SELECT seq, type, payload FROM events WHERE task_id = ? AND seq > ? ORDER BY seq",
            (task_id, last_sent),
        )
        for r in rows:
            last_sent = r["seq"]
            yield f"id: {r['seq']}\nevent: {r['type']}\ndata: {r['payload']}\n\n"

        status = db.query_one("SELECT status FROM tasks WHERE id=?", (task_id,))["status"]
        if status in ("done", "error"):
            yield f"event: stream.closed\ndata: {{\"status\": \"{status}\"}}\n\n"
            return

        # 任务进行中：广播实时事件
        while True:
            row = q.get()
            if row is None:  # 哨兵：任务已终态
                break
            if row["seq"] <= last_sent:
                continue  # 已被 DB 补发覆盖
            last_sent = row["seq"]
            yield f"id: {row['seq']}\nevent: {row['type']}\ndata: {row['payload']}\n\n"
        yield f"event: stream.closed\ndata: {{}}\n\n"
    finally:
        subs.get(task_id, []).remove(q)


@app.get("/api/research/{task_id}/events")
def task_sse(
    task_id: int,
    user: dict = Depends(_auth_from_query),
    last_event_id: str = Query(default="", alias="Last-Event-ID"),
):
    """SSE 端点（EventSource 用）：token 走 ?token= 查询参数。"""
    _require_task_owner(task_id, user)
    return StreamingResponse(
        sse_stream(task_id, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ---------- 静态前端 ----------
# no-cache：改前端代码后刷新立即生效，避免浏览器缓存旧版页面
@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-cache"
    return resp

app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")

