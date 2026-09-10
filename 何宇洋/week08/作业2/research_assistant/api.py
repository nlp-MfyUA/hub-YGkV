import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from .config import Settings
from .engine import Job, ResearchEngine
from .llm import DeepSeek
from .models import ResearchRequest
from .reporting import render_markdown
from .retrieval import Search, WebReader


def create_app(settings: Settings | None = None, engine=None) -> FastAPI:
    settings = settings or Settings.from_env()
    jobs: dict[str, Job] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine or ResearchEngine(
            settings, DeepSeek(settings) if not settings.configuration_errors() else None, Search(), WebReader())
        try:
            yield
        finally:
            tasks = [job.task for job in jobs.values() if job.task and not job.task.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await app.state.engine.close()

    app = FastAPI(title="深度研究助手", version="0.1.0", lifespan=lifespan)
    app.state.jobs = jobs

    def find_job(job_id: str) -> Job:
        if job_id not in jobs:
            raise HTTPException(404, "当前进程中不存在此任务")
        return jobs[job_id]

    @app.get("/health")
    async def health():
        errors = settings.configuration_errors()
        return {"status": "not_ready" if errors else "ready", "configuration_errors": errors}

    @app.post("/research", status_code=202)
    async def submit(request: ResearchRequest):
        if errors := settings.configuration_errors():
            raise HTTPException(503, errors)
        # 从检查到登记之间没有 await，单事件循环内不会并发接纳两个活动任务。
        if any(job.task and not job.task.done() for job in jobs.values()):
            raise HTTPException(409, "已有活动研究任务，请等待完成")
        job = Job(request=request, secret=settings.api_key)
        jobs[job.id] = job
        job.task = asyncio.create_task(app.state.engine.run(job), name=f"research-{job.id}")
        return {"id": job.id, "status": job.status, "status_url": f"/research/{job.id}"}

    @app.get("/research/{job_id}")
    async def status(job_id: str):
        return find_job(job_id).snapshot()

    @app.get("/research/{job_id}/events")
    async def events(job_id: str):
        job = find_job(job_id)
        return {"id": job.id, "events": job.events}

    @app.get("/research/{job_id}/report")
    async def report(job_id: str, format: Literal["json", "markdown"] = "json"):
        job = find_job(job_id)
        if job.report is None:
            raise HTTPException(409, "报告尚未生成")
        headers = {"Content-Disposition": f'attachment; filename="{job.id}.{"json" if format == "json" else "md"}"'}
        if format == "markdown":
            return PlainTextResponse(render_markdown(job.report), media_type="text/markdown", headers=headers)
        from fastapi.responses import JSONResponse
        return JSONResponse(job.report, headers=headers)

    return app


app = create_app()
