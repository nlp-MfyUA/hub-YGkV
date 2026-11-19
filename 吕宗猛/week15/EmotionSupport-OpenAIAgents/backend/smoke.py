"""命令行冒烟测试：不启动 Web，直接跑 OpenAI Agents 多 Agent 链路。

默认使用离线模拟模式，不需要模型网关：
    python smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# 默认离线；若要测真实网关：set MOCK_MODE=0 后再运行
os.environ.setdefault("MOCK_MODE", "1")

from pipeline import run_pipeline  # noqa: E402

CASES = [
    ("positive", "今天项目终于上线了，还被主管夸了，感觉这段时间的加班都值得。"),
    ("negative", "最近压力好大，什么都做不好，晚上也睡不着，觉得自己很没用。"),
    ("neutral", "周末打算去图书馆坐一下午，顺便把借的书还了。"),
]


async def run_case(expected: str, text: str) -> bool:
    print("=" * 72)
    print("输入：", text)
    label = ""
    reply = ""
    async for event in run_pipeline(text):
        if event["type"] == "emotion":
            label = event["label"]
            print(f"识别：{event['label_zh']} / 置信度 {event['confidence']:.0%} / 强度 {event['intensity']}/5")
            print(f"依据：{event['reason']}")
        elif event["type"] == "reply":
            reply = event["text"]
            print(f"回应 Agent：{event['agent_name']}")
            print("回应：")
            print(reply)
        elif event["type"] == "done":
            print(f"总耗时：{event['elapsed_ms']} ms")
    ok = label == expected and bool(reply)
    print("结果：", "PASS" if ok else f"FAIL（期望 {expected}，实际 {label}）")
    return ok


async def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(CASES)
    results = []
    for expected, text in CASES[:limit]:
        results.append(await run_case(expected, text))
    print("=" * 72)
    print(f"通过 {sum(results)}/{len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
