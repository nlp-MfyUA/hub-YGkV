"""openai-agents 版：一条命令起 4 个进程。

    python -m agents_version.run_all --demo     # 起服务 + 跑内置用例 + 退出
    python -m agents_version.run_all            # 起服务 + 交互式前端
    python -m agents_version.run_all --serve    # 只起服务，浏览器访问 8100
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import launch  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(launch.main("agents_version"))
