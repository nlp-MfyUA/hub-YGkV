# -*- coding: utf-8 -*-
"""入口：python3 main.py "研究主题" → 跑完整研究 → 报告写到 outputs/。"""
from __future__ import annotations

import logging
import sys

from deep_research import orchestrator, reporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "2026 年主流 AI Agent 框架对比"
    print(f"\n开始深度研究：{topic}\n")
    result = orchestrator.run(topic)
    path = reporter.save(result)
    print("\n" + "=" * 50)
    print(f"标题：{result.title}")
    print(f"正文分节：{len(result.sections)} | 来源：{len(result.sources)} | 置信度：{result.confidence.overall}")
    print(f"报告已保存：{path}")


if __name__ == "__main__":
    main()
