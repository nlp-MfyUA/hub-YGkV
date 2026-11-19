"""单容器入口：同时启动后端与前端两个进程。"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROCESSES: list[subprocess.Popen] = []


def start(script: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-u", str(ROOT / script)],
        cwd=str(ROOT),
    )


def shutdown(signum: int | None = None, _frame=None) -> None:
    for process in PROCESSES:
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 10
    for process in PROCESSES:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            process.kill()
    raise SystemExit(0 if signum is None else 128 + signum)


def _app_user():
    try:
        import pwd
        return pwd.getpwnam("appuser")
    except (ImportError, KeyError):
        return None


def ensure_database() -> None:
    """外挂目录没有 sessions.db（或文件为空）时，从镜像内置空库复制一份。"""
    raw = os.getenv("SESSION_DB_PATH", "./data/sessions.db")
    target = Path(raw) if Path(raw).is_absolute() else ROOT / raw
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.stat().st_size > 0:
        return

    seed = ROOT / "seed" / "init_sessions.db"
    if not seed.exists():
        print(f"[run_all] seed database not found: {seed}", flush=True)
        return

    try:
        shutil.copy2(seed, target)
        print(f"[run_all] initialized empty database: {target}", flush=True)
    except OSError as exc:
        print(f"[run_all] copy seed database failed: {exc}", flush=True)
        raise

    # 容器内 root 启动时，把外挂目录与数据库交给运行用户，避免后续写入失败
    user = _app_user()
    if user and hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            os.chown(target.parent, user.pw_uid, user.pw_gid)
            os.chown(target, user.pw_uid, user.pw_gid)
        except OSError as exc:
            print(f"[run_all] chown data directory failed: {exc}", flush=True)


def drop_privileges() -> None:
    """复制完数据后从 root 降权到 appuser。"""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    user = _app_user()
    if not user:
        return
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)


def main() -> None:
    ensure_database()
    drop_privileges()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    PROCESSES.append(start("backend/main.py"))
    # 留出后端初始化时间，避免前端首屏健康检查先失败
    time.sleep(1.0)
    PROCESSES.append(start("frontend/main.py"))

    while True:
        for process in PROCESSES:
            code = process.poll()
            if code is not None:
                print(f"[run_all] child exited with code {code}", flush=True)
                shutdown()
        time.sleep(0.5)


if __name__ == "__main__":
    main()