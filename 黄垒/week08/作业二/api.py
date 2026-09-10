"""深度研究助手 · FastAPI 服务

启动:
    uvicorn api:app --host 127.0.0.1 --port 8000    (须单进程运行，勿 --workers>1)

接口:
    POST /research     默认阻塞直取: 等研究跑完一次返回 4 类成品全文
                       请求体: {topic, max_subs?, max_rounds?=2, no_cache?=false,
                                "async"?=false, wait_timeout?(秒)}
                       async=true -> 立即返回 {job_id}（轮询模式）
                       阻塞超时(wait_timeout)未完成 -> 202 + {job_id, status:running}
                       研究失败 -> 500 + {job_id, error}
    GET  /jobs         列表，可选 ?status= & ?topic=<关键词>，默认创建时间倒序
    GET  /jobs/{id}    状态轮询: {status, stage, detail, ...}
    GET  /jobs/{id}/files 四类成品全文: {report, sources, process, confidence}

设计:
    默认一次调用拿到数据；底层仍是「提交任务 -> worker 串行执行 -> 完成事件唤醒」。
    job 成品落盘到 output/jobs/<job_id>/，进程重启后扫描该目录重建已完成任务；
    运行中的阻塞请求若客户端断开，研究不取消，仍可用 job_id 找回结果。
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import main as core

app = FastAPI(title="深度研究助手", version="1.1",
              description="输入研究主题，自动规划->检索->阅读->补检->综合，产出带来源引用的研究报告。")

BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "output" / "jobs"
_MAX_CONCURRENCY = 1  # 本地演示：完全串行，最省配额

app.state.jobs = {}
app.state.queue = queue.Queue()
app.state.lock = threading.Lock()
app.state.job_counter = 0
app.state._workers_started = False
app.state.events = {}  # job_id -> threading.Event，供阻塞请求等待完成


class ResearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    topic: str = Field(..., min_length=1, max_length=200, description="研究主题")
    max_subs: int | None = Field(None, ge=1, le=10, description="最多研究的子问题数")
    max_rounds: int = Field(2, ge=1, le=4, description="每个子问题最大检索轮次")
    no_cache: bool = Field(False, description="忽略磁盘缓存，强制重新检索/抓取")
    async_: bool = Field(False, alias="async",
                         description="true=立即返回 job_id（轮询）；false=阻塞直到完成")
    wait_timeout: float | None = Field(None, gt=0,
                                       description="阻塞等待秒数；null=无限等；超时返回 202")


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
                   "no_cache": req.no_cache, "async": req.async_,
                   "wait_timeout": req.wait_timeout},
    }
    app.state.jobs[job_id] = job
    app.state.events[job_id] = threading.Event()
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
    """后台工作线程：一次处理一个任务，跑完 set 完成事件唤醒阻塞请求。"""
    while True:
        job_id = app.state.queue.get()
        job = app.state.jobs.get(job_id)
        event = app.state.events.get(job_id)
        if job is None:
            if event:
                event.set()
            continue
        job["status"] = "running"
        job["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _dump_job(job)
        try:
            result = core.run_research(
                job["topic"],
                use_cache=not job["params"]["no_cache"],
                max_subs=job["params"]["max_subs"],
                max_rounds=job["params"]["max_rounds"],
                out_dir=Path(job["out_dir"]),
                on_stage=_set_stage(job_id),
            )
            job["stats"] = {"subs": result.get("subs"), "findings": result.get("findings"),
                            "sources": result.get("sources")}
        except Exception as e:
            job["status"] = "failed"
            job["stage"] = "failed"
            job["error"] = str(e)
        job["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if job["status"] != "failed":
            job["status"] = "done"
            job["stage"] = "done"
        _dump_job(job)
        if event:
            event.set()


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


def _get_job(job_id: str) -> dict:
    job = app.state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id} 不存在")
    return job


def _read_result_files(job: dict) -> dict:
    """从 job 落盘目录读 4 类成品全文；缺文件给空串。"""
    out_dir = Path(job["out_dir"])
    files = {}
    for key, fname in _FILE_NAMES.items():
        fp = out_dir / fname
        files[key] = fp.read_text(encoding="utf-8") if fp.exists() else ""
    return files


def _job_summary(job: dict) -> dict:
    return {
        "job_id": job["job_id"], "topic": job["topic"],
        "status": job["status"], "stage": job.get("stage"),
        "created": job.get("created"), "started": job.get("started"),
        "finished": job.get("finished"),
    }


@app.post("/research")
def submit_research(req: ResearchRequest) -> dict:
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic 不能为空")
    job_id = _new_job_id()
    _register_job(job_id, topic, req)
    app.state.queue.put(job_id)

    if req.async_:
        # 异步模式：立即返回 job_id，调用方轮询 /jobs/{id}
        return {"job_id": job_id, "topic": topic, "status": "queued"}

    # 阻塞模式：等完成事件，一次拿全量成品
    event = app.state.events[job_id]
    event.wait(timeout=req.wait_timeout)
    job = app.state.jobs[job_id]

    if job["status"] == "done":
        return {"job_id": job_id, "topic": topic, "status": "done",
                "stats": _read_stats(job),
                "summary": _job_summary(job),
                "files": _read_result_files(job)}
    if job["status"] == "failed":
        raise HTTPException(status_code=500,
                            detail={"job_id": job_id, "status": "failed",
                                    "error": job.get("error")})
    # 仍在 running/queued（wait_timeout 到期）
    return JSONResponse(status_code=202,
                        content={"job_id": job_id, "topic": topic, "status": job["status"],
                                 "stage": job.get("stage"), "detail": job.get("detail"),
                                 "message": "研究仍在进行，可用 GET /jobs/{id} 轮询或稍后重取"})


def _read_stats(job: dict) -> dict:
    """读取 worker 完成时写入的统计；重启恢复的任务拿不到则返回空结构。"""
    stats = job.get("stats")
    if stats:
        return stats
    return {"subs": None, "findings": None, "sources": None}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = _get_job(job_id)
    return {**_job_summary(job),
            "detail": job.get("detail"),
            "error": job.get("error"),
            "out_dir": job.get("out_dir"),
            "params": job.get("params")}


_FILE_NAMES = {"report": "report.md", "sources": "sources.md",
               "process": "process.md", "confidence": "confidence.md"}


@app.get("/jobs/{job_id}/files")
def job_files(job_id: str) -> dict:
    job = _get_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409,
                            detail=f"job 尚未完成，当前状态: {job['status']} / {job.get('stage')}")
    return {"job_id": job_id, "topic": job["topic"], "files": _read_result_files(job)}


@app.get("/jobs")
def list_jobs(status: str | None = None, topic: str | None = None) -> dict:
    jobs = list(app.state.jobs.values())
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    if topic:
        jobs = [j for j in jobs if topic in (j.get("topic") or "")]
    jobs.sort(key=lambda j: j.get("created") or "", reverse=True)
    return {"jobs": [_job_summary(j) for j in jobs]}
