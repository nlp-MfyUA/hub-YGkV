"""后端进程（OpenAI-Agents 版）：接收前端输入，串联进程1和进程2。"""

from __future__ import annotations

from common.service_helpers import create_backend_app, run_uvicorn

app = create_backend_app(
    framework="openai-agents",
    default_p1_url="http://127.0.0.1:8101",
    default_p2_url="http://127.0.0.1:8102",
)

if __name__ == "__main__":
    run_uvicorn(app, default_port=8100, description="OpenAI-Agents 后端进程：串联进程1和进程2")
