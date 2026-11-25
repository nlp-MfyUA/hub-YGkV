"""一键启动 OpenAI-Agents 版 4 个独立进程（进程1 + 进程2 + 后端进程 + 前端进程）。"""

from __future__ import annotations

from common.service_helpers import launch_stack

if __name__ == "__main__":
    launch_stack(
        module_prefix="openai_agents_impl",
        framework_label="OpenAI-Agents",
        p1_port=8101,
        p2_port=8102,
        backend_port=8100,
    )
