# -*- coding: utf-8 -*-
"""main —— 命令行入口：python main.py "研究主题"。"""
from __future__ import annotations

import asyncio
import logging
import sys

import research


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    )
    if len(sys.argv) < 2:
        print("用法: python main.py \"研究主题\"")
        sys.exit(1)
    topic = sys.argv[1]
    print(f"开始研究：{topic}\n")

    result = await research.run_research(topic, on_event=print)

    print("\n" + "=" * 60)
    path = research.save_report(topic, result)
    print(f"报告已保存: {path}")


if __name__ == "__main__":
    asyncio.run(main())
