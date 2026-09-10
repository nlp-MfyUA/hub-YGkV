# -*- coding: utf-8 -*-
"""api —— 极简 FastAPI 接口：POST 发起研究（后台执行），GET 轮询结果。

启动: uvicorn api:app --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import research

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
)

app = FastAPI(title="Deep Research API")

# 内存存储：research_id -> {status, topic, logs, result}
STORE: dict[str, dict] = {}


class ResearchReq(BaseModel):
    topic: str


async def _run_task(rid: str, topic: str) -> None:
    record = STORE[rid]

    def on_event(text: str) -> None:
        record["logs"].append(text)

    try:
        record["status"] = "running"
        record["result"] = await research.run_research(topic, on_event=on_event)
        record["status"] = "completed"
    except Exception as exc:  # noqa: BLE001
        logging.exception("研究任务失败 rid=%s", rid)
        record["status"] = "failed"
        record["error"] = str(exc)


@app.get("/")
async def index():
    """前端页面：输入主题发起研究，实时看过程日志和报告。"""
    return FileResponse(Path(__file__).resolve().parent / "index.html")


@app.post("/api/research")
async def start_research(req: ResearchReq):
    """发起一次研究，立即返回 research_id，后台执行。"""
    rid = uuid.uuid4().hex[:12]
    STORE[rid] = {"status": "pending", "topic": req.topic, "logs": [], "result": None}
    asyncio.create_task(_run_task(rid, req.topic))
    return {"research_id": rid, "status": "pending"}


@app.get("/api/research/{rid}")
async def get_research(rid: str):
    """轮询研究状态与结果（pending / running / completed / failed）。"""
    record = STORE.get(rid)
    if record is None:
        return {"error": "not found"}
    resp = {"research_id": rid, "status": record["status"], "topic": record["topic"]}
    if record["status"] == "completed":
        resp["report"] = record["result"]["report"]
        resp["sources"] = [
            {"ref": s["ref"], "title": s["title"], "url": s["url"]} for s in record["result"]["sources"]
        ]
    if record["status"] == "failed":
        resp["error"] = record.get("error")
    resp["logs"] = record["logs"]
    return resp
