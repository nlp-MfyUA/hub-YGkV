"""一键启动 LangGraph 版 4 个独立进程（进程1 + 进程2 + 后端进程 + 前端进程）。"""

from __future__ import annotations

from common.service_helpers import launch_stack

if __name__ == "__main__":
    launch_stack(
        module_prefix="langgraph_impl",
        framework_label="LangGraph",
        p1_port=8001,
        p2_port=8002,
        backend_port=8000,
    )
