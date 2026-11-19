"""openai-agents 版冒烟测试：python -m agents_version.smoke_test"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.smoke import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("agents_version"))
