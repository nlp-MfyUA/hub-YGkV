"""命令行单图测试：先跑通模型，再动前端。

用法:
    python -m app.test_vl path/to/hallway.jpg
    python -m app.test_vl path/to/hallway.jpg qwen
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.analyzer import analyze  # noqa: E402
from app.llm import DEFAULT_PROVIDER, RISK_LABELS_CN  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    img_path = Path(sys.argv[1])
    provider = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PROVIDER

    if not img_path.exists():
        print(f"文件不存在: {img_path}")
        return 2

    print(f"图片: {img_path}")
    print(f"供应商: {provider}")
    print("-" * 50)

    result, latency = analyze(img_path.read_bytes(), provider)

    print(f"是否楼道 : {result.is_hallway}")
    print(f"风险等级 : {result.risk_level} ({RISK_LABELS_CN.get(result.risk_level, '?')})")
    print(f"风险分数 : {result.risk_score}")
    print(f"隐患元素 : {result.hazards}")
    print(f"观察内容 : {result.observations}")
    print(f"判定依据 : {result.reason}")
    print(f"整改建议 : {result.advice}")
    print(f"耗时     : {latency} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
