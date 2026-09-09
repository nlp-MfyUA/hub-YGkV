"""深度研究助手 · FastAPI 服务

启动:
    uvicorn api:app --host 127.0.0.1 --port 8000

接口:
    POST /research       {topic, max_subs?, max_rounds?, no_cache?} -> {job_id}
    GET  /jobs/{id}      状态轮询: {status, stage, detail, ...}
    GET  /jobs/{id}/files 四类成品全文: {report, sources, process, confidence}

设计:
    研究耗时数分钟，采用「提交任务 -> 轮询状态 -> 取成品」的异步模型。
    任务串行执行（并发上限默认 1），job 成品落盘到 output/jobs/<job_id>/，
    进程重启后通过扫描该目录重建已完成任务。
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import main as core

app = FastAPI(title="深度研究助手", version="1.0",
              description="输入研究主题，后台自动规划->检索->阅读->补检->综合，产出带来源引用的研究报告。")

BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "output" / "jobs"
_MAX_CONCURRENCY = 1  # 本地演示：完全串行，最省配额

app.state.jobs = {}
app.state.queue = queue.Queue()
app.state.lock = threading.Lock()
app.state.job_counter = 0
app.state._workers_started = False


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200, description="研究主题")
    max_subs: int | None = Field(None, ge=1, le=10, description="最多研究的子问题数")
    max_rounds: int = Field(2, ge=1, le=4, description="每个子问题最大检索轮次")
    no_cache: bool = Field(False, description="忽略磁盘缓存，强制重新检索/抓取")


def _new_job_id() -> str:
    with app.state.lock:
        app.state.job_counter += 1
        n = app.state.job_counter
    return f"job-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}-{n:04d}"


def _job_out_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _register_job(job_id: str, topic: str, req: ResearchRequest) -> dict:
    out_dir = _job_out_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id, "topic": topic,
        "status": "queued", "stage": "queued", "detail": "等待空闲任务位",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "started": None, "finished": None,
        "error": None, "out_dir": str(out_dir),
        "params": {"max_subs": req.max_subs, "max_rounds": req.max_rounds,
                   "no_cache": req.no_cache},
    }
    app.state.jobs[job_id] = job
    (out_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    return job


def _dump_job(job: dict) -> None:
    p = Path(job["out_dir"]) / "job.json"
    p.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_stage(job_id: str):
    def handler(stage: str, detail: str) -> None:
        job = app.state.jobs.get(job_id)
        if not job:
            return
        job["status"] = "done" if stage == "done" else "running"
        job["stage"] = stage
        job["detail"] = detail
    return handler


def _worker() -> None:
    """后台工作线程：一次处理一个任务，跑完接着取下一个。"""
    while True:
        job_id = app.state.queue.get()
        job = app.state.jobs.get(job_id)
        if job is None:
            continue
        job["status"] = "running"
        job["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _dump_job(job)
        try:
            core.run_research(
                job["topic"],
                use_cache=not job["params"]["no_cache"],
                max_subs=job["params"]["max_subs"],
                max_rounds=job["params"]["max_rounds"],
                out_dir=Path(job["out_dir"]),
                on_stage=_set_stage(job_id),
            )
        except Exception as e:
            job["status"] = "failed"
            job["stage"] = "failed"
            job["error"] = str(e)
        job["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if job["status"] != "failed":
            job["status"] = "done"
            job["stage"] = "done"
        _dump_job(job)


def _spawn_workers() -> None:
    if not getattr(app.state, "_workers_started", False):
        with app.state.lock:
            if not app.state._workers_started:
                for _ in range(_MAX_CONCURRENCY):
                    t = threading.Thread(target=_worker, daemon=True)
                    t.start()
                app.state._workers_started = True


@app.on_event("startup")
def _startup() -> None:
    _spawn_workers()
    _rebuild_from_disk()


def _rebuild_from_disk() -> None:
    """启动时扫描 output/jobs/，把磁盘上已完成/失败的任务恢复到内存索引。"""
    if not JOBS_DIR.exists():
        return
    for jf in JOBS_DIR.glob("*/job.json"):
        try:
            job = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("status") in ("running", "queued"):
            # 进程重启后这些任务已不可续跑，标记为失败并说明
            job["status"] = "failed"
            job["stage"] = "interrupted_by_restart"
            job["error"] = job.get("error") or "服务重启，任务中断，可用 --synth-only 或重提交"
        elif job.get("status") == "done":
            job["stage"] = "done"
        app.state.jobs[job["job_id"]] = job


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/research")
def submit_research(req: ResearchRequest) -> dict:
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic 不能为空")
    job_id = _new_job_id()
    _register_job(job_id, topic, req)
    app.state.queue.put(job_id)
    return {"job_id": job_id, "topic": topic, "status": "queued"}


def _get_job(job_id: str) -> dict:
    job = app.state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id} 不存在")
    return job


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = _get_job(job_id)
    return {
        "job_id": job_id,
        "topic": job["topic"],
        "status": job["status"],
        "stage": job.get("stage"),
        "detail": job.get("detail"),
        "created": job.get("created"),
        "started": job.get("started"),
        "finished": job.get("finished"),
        "error": job.get("error"),
        "out_dir": job.get("out_dir"),
        "params": job.get("params"),
    }


_FILE_NAMES = {"report": "report.md", "sources": "sources.md",
               "process": "process.md", "confidence": "confidence.md"}


@app.get("/jobs/{job_id}/files")
def job_files(job_id: str) -> dict:
    job = _get_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409,
                            detail=f"job 尚未完成，当前状态: {job['status']} / {job.get('stage')}")
    out_dir = Path(job["out_dir"])
    files = {}
    for key, fname in _FILE_NAMES.items():
        fp = out_dir / fname
        files[key] = fp.read_text(encoding="utf-8") if fp.exists() else ""
    return {"job_id": job_id, "topic": job["topic"], "files": files}


@app.get("/jobs")
def list_jobs() -> dict:
    return {"jobs": [{"job_id": j["job_id"], "topic": j["topic"], "status": j["status"],
                      "stage": j.get("stage"), "created": j.get("created")}
                     for j in app.state.jobs.values()]}
