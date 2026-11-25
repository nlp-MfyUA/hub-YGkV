"""前端进程（LangGraph 版）：接收用户输入并请求后端进程。"""

from __future__ import annotations

from common.service_helpers import run_frontend_cli

if __name__ == "__main__":
    run_frontend_cli(framework="LangGraph", default_backend_url="http://127.0.0.1:8000")
