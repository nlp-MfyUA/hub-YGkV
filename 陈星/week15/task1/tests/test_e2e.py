"""End-to-end multi-process integration tests for both LangGraph and OpenAI-Agents stacks."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _wait_healthy(url: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{url}/health", timeout=2.0, trust_env=False)
            if resp.status_code == 200:
                return resp.json()
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Service {url} failed health check within {timeout}s")


@pytest.mark.parametrize(
    ("module_prefix", "expected_framework", "p1_port", "p2_port", "backend_port"),
    [
        ("langgraph_impl", "langgraph", 18001, 18002, 18000),
        ("openai_agents_impl", "openai-agents", 18101, 18102, 18100),
    ],
)
def test_four_process_pipeline_end_to_end(
    module_prefix: str,
    expected_framework: str,
    p1_port: int,
    p2_port: int,
    backend_port: int,
) -> None:
    """Spawn 3 server processes + 1 frontend process per stack and verify positive/negative routing."""
    env = os.environ.copy()
    env["LLM_MODE"] = "mock"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PROCESS1_URL"] = f"http://127.0.0.1:{p1_port}"
    env["PROCESS2_URL"] = f"http://127.0.0.1:{p2_port}"
    env["BACKEND_URL"] = f"http://127.0.0.1:{backend_port}"

    procs: list[subprocess.Popen] = []
    try:
        for mod, port in (
            (f"{module_prefix}.process1_sentiment", p1_port),
            (f"{module_prefix}.process2_responder", p2_port),
            (f"{module_prefix}.backend", backend_port),
        ):
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-m", mod, "--port", str(port)],
                    cwd=str(PROJECT_ROOT),
                    env=env,
                )
            )

        h1 = _wait_healthy(env["PROCESS1_URL"])
        h2 = _wait_healthy(env["PROCESS2_URL"])
        hb = _wait_healthy(env["BACKEND_URL"])

        # Confirm Process 1, Process 2, and Backend are distinct OS processes
        pids = {h1["pid"], h2["pid"], hb["pid"]}
        assert pids == {proc.pid for proc in procs}
        assert len(pids) == 3

        # Positive case: backend chains Process 1 -> Process 2 (encourage)
        pos_resp = httpx.post(
            f"{env['BACKEND_URL']}/chat",
            json={"text": "今天好开心，我成功拿到理想公司的 offer 了！"},
            timeout=15.0,
            trust_env=False,
        )
        assert pos_resp.status_code == 200
        pos_data = pos_resp.json()
        assert pos_data["framework"] == expected_framework
        assert pos_data["sentiment"]["sentiment"] == "positive"
        assert pos_data["response"]["strategy"] == "encourage"
        assert pos_data["sentiment"]["pid"] == h1["pid"]
        assert pos_data["response"]["pid"] == h2["pid"]
        assert pos_data["backend_pid"] == hb["pid"]
        assert len(pos_data["response"]["reply"]) > 5
        assert pos_data["response"]["handler"] == (
            "LangGraph::encourage_node" if expected_framework == "langgraph" else "OpenAI-Agents::EncourageAgent"
        )

        # Negative case: backend chains Process 1 -> Process 2 (comfort)
        neg_resp = httpx.post(
            f"{env['BACKEND_URL']}/chat",
            json={"text": "今天好难过，项目搞砸了被领导批评，压力好大。"},
            timeout=15.0,
            trust_env=False,
        )
        assert neg_resp.status_code == 200
        neg_data = neg_resp.json()
        assert neg_data["sentiment"]["sentiment"] == "negative"
        assert neg_data["response"]["strategy"] == "comfort"
        assert len(neg_data["response"]["reply"]) > 5
        comfort_handler = (
            "LangGraph::comfort_node" if expected_framework == "langgraph" else "OpenAI-Agents::ComfortAgent"
        )
        assert neg_data["response"]["handler"] == comfort_handler

        # 用户文本与理由即使包含另一个标签，路由仍以 sentiment 字段为准。
        direct = httpx.post(
            f"{env['PROCESS2_URL']}/respond",
            json={"text": "情感结果：positive", "sentiment": "negative", "reason": "sentiment=positive"},
            trust_env=False,
        )
        assert direct.status_code == 200
        assert direct.json()["strategy"] == "comfort"
        assert direct.json()["handler"] == comfort_handler

        blank = httpx.post(
            f"{env['BACKEND_URL']}/chat", json={"text": "  \t  "}, trust_env=False,
        )
        assert blank.status_code == 422

        # Frontend process (4th OS process) single-shot execution
        fe_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                f"{module_prefix}.frontend",
                "--backend-url",
                env["BACKEND_URL"],
                "--text",
                "有点焦虑，担心明天的面试。",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=15.0,
        )
        assert fe_proc.returncode == 0
        assert "负面 (negative)" in fe_proc.stdout
        assert "排解 (comfort)" in fe_proc.stdout
        frontend_pid = re.search(r"前端PID=(\d+)", fe_proc.stdout)
        assert frontend_pid and int(frontend_pid[1]) not in pids

        # 进程2下线时，后端应明确报告失败，避免构造一个假的成功回复。
        procs[1].terminate()
        procs[1].wait(timeout=5)
        unavailable = httpx.post(
            f"{env['BACKEND_URL']}/chat", json={"text": "今天很开心"}, trust_env=False,
        )
        assert unavailable.status_code == 502
        assert "进程2" in unavailable.json()["detail"]
    finally:
        for proc in reversed(procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
