"""命令行自测：逐问跑完整流程，打印各阶段耗时与最终答案。

用法：
    python smoke.py "2010 年各国销售额前 5 名" "哪位员工负责的客户最多"
"""

from __future__ import annotations

import asyncio
import sys

from pipeline import run_pipeline


async def run_one(question: str) -> None:
    print("=" * 78)
    print(f"问：{question}")
    answer = ""
    async for event in run_pipeline(question):
        if event["type"] == "stage":
            payload = event.get("payload", {})
            extra = ""
            if event["stage"] == "generate" and event["status"] == "done":
                extra = f" round={payload.get('round')} sql={payload.get('sql', '')[:60]!r}"
            elif event["stage"] == "check" and event["status"] == "done":
                extra = f" approved={payload.get('approved')} source={payload.get('source')}"
                if payload.get("issues"):
                    extra += f" issues={payload['issues']}"
            elif event["stage"] == "execute" and event["status"] == "done":
                extra = f" rows={payload.get('row_count')} cols={payload.get('columns')}"
            print(f"  [{event['stage']:<9}] {event['status']:<7} {event['elapsed_ms']:>6}ms{extra}")
        elif event["type"] == "delta":
            answer += event["text"]
        elif event["type"] == "done":
            payload = event["payload"]
            print(f"  -> {payload['total_ms']}ms / {payload['rounds']} 轮 / {payload['usage'].get('total_tokens')} tokens")
        elif event["type"] == "error":
            print(f"  !! {event['payload']}")
    print(f"答：{answer}\n")


async def main() -> None:
    questions = sys.argv[1:] or ["2010 年各国销售额前 5 名，并给出订单数"]
    for question in questions:
        await run_one(question)


if __name__ == "__main__":
    asyncio.run(main())
