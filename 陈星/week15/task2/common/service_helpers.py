"""Shared HTTP backend chaining, CLI frontend, and multi-process launcher helpers."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TypeVar

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.schemas import (
    ChatRequest,
    ChatResponse,
    RespondRequest,
    RespondResponse,
    SentimentRequest,
    SentimentResponse,
)


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
STAGE_TIMEOUT = 50.0


async def _post_stage(
    client: httpx.AsyncClient,
    url: str,
    payload: BaseModel,
    response_type: type[ResponseModel],
    label: str,
) -> ResponseModel:
    try:
        response = await client.post(url, json=payload.model_dump())
        response.raise_for_status()
        return response_type.model_validate(response.json())
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"{label}响应超时。") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"{label}调用失败或返回无效数据。") from exc


def create_backend_app(
    framework: str,
    default_p1_url: str,
    default_p2_url: str,
) -> FastAPI:
    """Build the backend FastAPI app that chains Process 1 -> Process 2 over HTTP."""
    p1_url = os.getenv("PROCESS1_URL", default_p1_url).rstrip("/")
    p2_url = os.getenv("PROCESS2_URL", default_p2_url).rstrip("/")

    app = FastAPI(title=f"{framework} Backend Orchestrator")

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "framework": framework,
            "process": "backend",
            "pid": os.getpid(),
            "process1_url": p1_url,
            "process2_url": p2_url,
        }

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        async with httpx.AsyncClient(timeout=STAGE_TIMEOUT, trust_env=False) as client:
            sentiment_data = await _post_stage(
                client, f"{p1_url}/analyze", SentimentRequest(text=req.text),
                SentimentResponse, "进程1（情感识别）",
            )
            respond_request = RespondRequest(
                text=req.text, sentiment=sentiment_data.sentiment, reason=sentiment_data.reason,
            )
            respond_data = await _post_stage(
                client, f"{p2_url}/respond", respond_request,
                RespondResponse, "进程2（情绪回应）",
            )

        expected = "encourage" if sentiment_data.sentiment == "positive" else "comfort"
        if respond_data.sentiment != sentiment_data.sentiment or respond_data.strategy != expected:
            raise HTTPException(status_code=502, detail="进程2返回的策略与进程1标签不一致。")

        return ChatResponse(
            input_text=req.text,
            sentiment=sentiment_data,
            response=respond_data,
            framework=framework,
            backend_pid=os.getpid(),
        )

    return app


def run_uvicorn(app: FastAPI, default_port: int, description: str) -> None:
    """Parse --port / PORT env var and run uvicorn."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", str(default_port))))
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def _print_result(data: ChatResponse, frontend_pid: int) -> None:
    sentiment_cn = "正向 (positive)" if data.sentiment.sentiment == "positive" else "负面 (negative)"
    strategy_cn = "鼓励 (encourage)" if data.response.strategy == "encourage" else "排解 (comfort)"
    print("\n" + "=" * 60)
    print(f"[{data.framework}] 链路调用完成 (前端PID={frontend_pid} -> 后端PID={data.backend_pid} -> 进程1 PID={data.sentiment.pid} -> 进程2 PID={data.response.pid})")
    print(f"进程1 情感识别: {sentiment_cn} | 置信度参考值: {data.sentiment.confidence:.2f}")
    print(f"进程1 判断依据: {data.sentiment.reason}")
    print(f"进程2 路由策略: {strategy_cn} (执行者: {data.response.handler})")
    print(f"进程2 回复内容: {data.response.reply}")
    print("=" * 60 + "\n")


def run_frontend_cli(framework: str, default_backend_url: str) -> None:
    """Interactive CLI frontend process accepting user input and calling Backend."""
    parser = argparse.ArgumentParser(description=f"{framework} 前端用户输入进程")
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", default_backend_url))
    parser.add_argument("--text", default=None, help="单次输入文本（非交互模式）")
    args = parser.parse_args()

    backend_url = args.backend_url.rstrip("/")
    frontend_pid = os.getpid()

    def send_once(user_text: str) -> bool:
        try:
            payload = ChatRequest(text=user_text)
        except ValueError:
            print("请输入至少一个非空白字符。", file=sys.stderr)
            return False
        try:
            resp = httpx.post(
                f"{backend_url}/chat",
                json=payload.model_dump(),
                timeout=2 * STAGE_TIMEOUT + 5,
                trust_env=False,
            )
            resp.raise_for_status()
            data = ChatResponse.model_validate(resp.json())
        except httpx.HTTPStatusError as exc:
            print(f"后端请求失败（HTTP {exc.response.status_code}）。", file=sys.stderr)
            return False
        except (httpx.RequestError, ValueError):
            print("无法连接后端或读取结果，请检查服务是否运行。", file=sys.stderr)
            return False
        _print_result(data, frontend_pid)
        return True

    if args.text is not None:
        if not send_once(args.text):
            raise SystemExit(1)
        return

    print(f"=== {framework} 情感陪伴系统 前端进程 (PID={frontend_pid}) ===")
    print(f"已连接后端地址: {backend_url}")
    print("请输入你想说的话（输入 quit / exit / 退出 结束）：")
    while True:
        try:
            user_text = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n前端进程退出。")
            break
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit", "q", "退出"}:
            print("再见！")
            break
        send_once(user_text)


def _wait_healthy(url: str, name: str, proc: subprocess.Popen, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{name}已退出（退出码 {proc.returncode}），请检查启动日志。")
        try:
            resp = httpx.get(f"{url}/health", timeout=2.0, trust_env=False)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("pid") == proc.pid:
                    return data
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{name} ({url}) 启动超时")


def launch_stack(
    module_prefix: str,
    framework_label: str,
    p1_port: int,
    p2_port: int,
    backend_port: int,
) -> None:
    """Spawn Process 1, Process 2, Backend, and Frontend as 4 separate OS processes."""
    parser = argparse.ArgumentParser(description=f"一键启动 {framework_label} 四进程系统")
    parser.add_argument("--text", default=None, help="传入单条测试文本后自动退出")
    args = parser.parse_args()

    project_root = str(Path(__file__).resolve().parent.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    env["PROCESS1_URL"] = f"http://127.0.0.1:{p1_port}"
    env["PROCESS2_URL"] = f"http://127.0.0.1:{p2_port}"
    env["BACKEND_URL"] = f"http://127.0.0.1:{backend_port}"

    procs: list[subprocess.Popen] = []
    try:
        p1 = subprocess.Popen(
            [sys.executable, "-m", f"{module_prefix}.process1_sentiment", "--port", str(p1_port)],
            cwd=project_root,
            env=env,
        )
        procs.append(p1)

        p2 = subprocess.Popen(
            [sys.executable, "-m", f"{module_prefix}.process2_responder", "--port", str(p2_port)],
            cwd=project_root,
            env=env,
        )
        procs.append(p2)

        backend = subprocess.Popen(
            [sys.executable, "-m", f"{module_prefix}.backend", "--port", str(backend_port)],
            cwd=project_root,
            env=env,
        )
        procs.append(backend)

        h1 = _wait_healthy(env["PROCESS1_URL"], "进程1(情感识别)", p1)
        h2 = _wait_healthy(env["PROCESS2_URL"], "进程2(情绪回应)", p2)
        hb = _wait_healthy(env["BACKEND_URL"], "后端进程", backend)

        print(f"[{framework_label}] 后台三进程已就绪:")
        print(f"  - 进程1 (情感识别): PID={h1['pid']} @ {env['PROCESS1_URL']}")
        print(f"  - 进程2 (情绪回应): PID={h2['pid']} @ {env['PROCESS2_URL']}")
        print(f"  - 后端进程 (串联):   PID={hb['pid']} @ {env['BACKEND_URL']}", flush=True)

        frontend_cmd = [
            sys.executable,
            "-m",
            f"{module_prefix}.frontend",
            "--backend-url",
            env["BACKEND_URL"],
        ]
        if args.text is not None:
            frontend_cmd.extend(["--text", args.text])

        frontend = subprocess.Popen(frontend_cmd, cwd=project_root, env=env)
        procs.append(frontend)
        exit_code = frontend.wait()
        if exit_code:
            raise SystemExit(exit_code)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    finally:
        for proc in reversed(procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
