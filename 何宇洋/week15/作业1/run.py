"""启动并监管四个独立子进程；Ctrl+C 或任何子进程退出时清理整组进程。"""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", choices=["langgraph", "openai-agents"], default="openai-agents")
    parser.add_argument("--base-port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="前端监听地址；Docker 中使用 0.0.0.0")
    args = parser.parse_args()
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        parser.error("请先设置环境变量 DEEPSEEK_API_KEY")
    if not 1024 <= args.base_port <= 65532:
        parser.error("base-port 必须在 1024 到 65532 之间")
    # 提前发现端口占用，避免留下只启动了一半的服务。
    for port in range(args.base_port, args.base_port + 4):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"端口 {port} 已被占用，请使用 --base-port 更换端口组")
    env = os.environ.copy()
    for role, offset in [("backend", 1), ("sentiment", 2), ("response", 3)]:
        env[f"{role.upper()}_URL"] = f"http://127.0.0.1:{args.base_port + offset}"
    processes = []
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    exit_code = 0
    try:
        for role, offset in [("sentiment", 2), ("response", 3), ("backend", 1), ("frontend", 0)]:
            process = subprocess.Popen([
                sys.executable, "-m", "common.service", "--role", role,
                "--framework", args.framework, "--port", str(args.base_port + offset),
                "--host", args.host if role == "frontend" else "127.0.0.1",
            ], cwd=Path(__file__).resolve().parent, env=env)
            processes.append(process)
        print(f"前端地址：http://localhost:{args.base_port}（待 /health 返回 ok 后使用）", flush=True)
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f"子进程 {process.pid} 意外退出，退出码 {process.returncode}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        exit_code = 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
