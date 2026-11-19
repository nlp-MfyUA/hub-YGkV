"""四个进程的启动器（两个版本共用）。

    前端进程(python -m common.frontend_cli)
        │  HTTP
    后端进程(backend)  :8100
        ├── HTTP ──> 进程1(sentiment_service) :8101
        └── HTTP ──> 进程2(reply_service)     :8102

每个进程都是独立的 OS 进程（不是线程），互相之间只认 HTTP JSON。
这样既能本地起，也能一个进程一个容器。
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

from . import config, rpc

SERVICES: list[tuple[str, str, int]] = [
    ("进程1 情感识别", "sentiment_service", config.SENTIMENT_PORT),
    ("进程2 情绪回应", "reply_service", config.REPLY_PORT),
    ("后端 编排", "backend", config.BACKEND_PORT),
]

TARGETS = {
    "进程1 情感识别": config.SENTIMENT_URL,
    "进程2 情绪回应": config.REPLY_URL,
    "后端 编排": config.BACKEND_URL,
}


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if extra:
        env.update(extra)
    return env


def spawn(pkg: str, module: str, env_extra: dict[str, str] | None = None) -> subprocess.Popen:
    cmd = [sys.executable, "-u", "-m", f"{pkg}.{module}"]
    return subprocess.Popen(cmd, cwd=str(config.ASSIGNMENT_DIR), env=_env(env_extra))


def _width(text: str) -> int:
    """中文按 2 个字符宽度算，否则三行标签对不齐。"""
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def _pad(text: str, cells: int) -> str:
    return text + " " * max(0, cells - _width(text))


def start_all(pkg: str) -> list[subprocess.Popen]:
    print("\n启动进程（每个都是独立 OS 进程）：", flush=True)
    procs = []
    for label, module, port in SERVICES:
        proc = spawn(pkg, module)
        procs.append(proc)
        print(f"  · {_pad(label, 16)} pid={proc.pid}   port={port}", flush=True)
        time.sleep(0.15)
    return procs


def stop_all(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 8
    for proc in procs:
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
    print("已停止全部子进程。", flush=True)


def run_frontend(args: list[str]) -> int:
    cmd = [sys.executable, "-u", "-m", "common.frontend_cli", *args]
    return subprocess.call(cmd, cwd=str(config.ASSIGNMENT_DIR), env=_env())


def main(pkg: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 4 进程链路")
    parser.add_argument("--demo", action="store_true", help="跑内置用例后退出")
    parser.add_argument("--serve", action="store_true", help="只起服务，常驻（Ctrl+C 退出）")
    parser.add_argument("--keep", action="store_true", help="前端结束后不关闭服务")
    args = parser.parse_args(argv)

    if not config.has_llm():
        print("! 没有检测到 LLM_API_KEY，将走规则兜底（链路仍可跑通）。", flush=True)

    procs = start_all(pkg)
    exit_code = 0

    def _graceful(signum, frame):  # noqa: ANN001, ARG001
        print("\n收到退出信号…", flush=True)
        stop_all(procs)
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _graceful)
        except (ValueError, OSError):
            pass

    try:
        rpc.wait_until_healthy(TARGETS)
        print(f"\n链路就绪，网页前端： http://127.0.0.1:{config.BACKEND_PORT}\n", flush=True)
        if args.serve:
            while True:
                time.sleep(1)
        elif args.demo:
            exit_code = run_frontend(["--demo"])
        else:
            exit_code = run_frontend([])
    except rpc.RpcError as exc:
        print(f"\n启动失败：{exc}", flush=True)
        exit_code = 1
    finally:
        if not args.keep:
            stop_all(procs)
        else:
            print("服务仍在运行，Ctrl+C 结束。", flush=True)
    return exit_code
