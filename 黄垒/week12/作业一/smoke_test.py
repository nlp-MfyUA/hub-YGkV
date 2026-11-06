"""命令行冒烟测试：不走网页，直接把本地图片丢给视觉模型。

用法：
    python smoke_test.py 图片.jpg
    python smoke_test.py 图片1.jpg 图片2.jpg --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from image_utils import ImageError, prepare_image  # noqa: E402
from vision import VisionClient, VisionError  # noqa: E402

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="楼道消防隐患识别 · 命令行测试")
    parser.add_argument("images", nargs="+", help="一张或多张本地图片")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    try:
        client = VisionClient()
    except VisionError as exc:
        print(f"初始化失败：{exc}")
        return 2

    failed = 0
    for image_path in args.images:
        path = Path(image_path)
        print(f"\n=== {path.name} ===")
        try:
            jpeg, mime, size = prepare_image(path.read_bytes())
            assessment, repairs = client.analyze(jpeg, mime)
        except (OSError, ImageError, VisionError) as exc:
            print(f"识别失败：{exc}")
            failed += 1
            continue

        if args.json:
            print(assessment.model_dump_json(indent=2))
            continue

        print(f"图片：{size}，压缩后 {len(jpeg) // 1024}KB" + ("（触发过一次修复）" if repairs else ""))
        print(f"等级：{assessment.risk_level.value}  分数：{assessment.risk_score}  把握度：{assessment.confidence}")
        print(f"场景：{assessment.scene}")
        print(f"结论：{assessment.summary}")
        for finding in assessment.findings:
            print(f"  - [{finding.severity}] {finding.category}：{finding.description}")
        for suggestion in assessment.suggestions:
            print(f"  ✓ {suggestion}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
