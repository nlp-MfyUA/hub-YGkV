"""前端进程：用户输入的唯一入口。

它只做三件事：收输入、把输入发给后端、把后端的链路结果渲染出来。
真正的「理解」和「安慰」不在这个进程里——这样前端换 CLI / 网页 / 小程序都不用动后端。

用法：
    python -m common.frontend_cli                     # 交互模式
    python -m common.frontend_cli --demo              # 跑内置 6 条用例
    python -m common.frontend_cli --demo --no-stream   # 不用 SSE，走一次性接口
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

from . import config

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


DIM, CYAN, GREEN, YELLOW, MAGENTA, RED, BOLD = "2", "36", "32", "33", "35", "31", "1"

STRATEGY_CN = {"encourage": "鼓励", "soothe": "排解", "listen": "倾听", "crisis": "危机兜底"}
LABEL_CN = {"positive": "正向", "negative": "负向", "neutral": "中性"}

DEMO_CASES = [
    "今天终于把拖了两周的项目交了，组长在会上点名夸了我一句！",
    "明天要答辩，PPT 还有十页没做完，感觉要完蛋了。",
    "刚把杯子放桌上了。",
    "又是加班到十点，真棒，这个月第六次了。",
    "谢谢你上次陪我聊到半夜，我这两天好多了。",
    "最近总觉得活着没什么意思，什么都不想做。",
]


def _bar(value: float, width: int = 10) -> str:
    filled = int(round(value * width))
    return "█" * filled + "·" * (width - filled)


def render_result(data: dict) -> None:
    """把一次完整结果（非流式）渲染成人能读的样子。"""
    s, r = data["sentiment"], data["reply"]
    label = f'{LABEL_CN.get(s["label"], s["label"])}/{s["label"]}'
    print(f'  ├─ {c("进程1 情感识别", CYAN)}  {c(label, YELLOW)}  {s["emotion"]}  '
          f'conf={s["confidence"]:.2f} 强度={s["intensity"]:.2f} {c(_bar(s["intensity"]), DIM)}')
    if s.get("reason"):
        print(f'  │    依据：{c(s["reason"], DIM)}')
    print(f'  ├─ {c("进程2 情绪回应", MAGENTA)}  {r["strategy"]}（{STRATEGY_CN.get(r["strategy"], r["strategy"])}）'
          f'  来源={r.get("source", "llm")}')
    print(f'  └─ {c("后端", GREEN)}  总耗时 {data.get("elapsed_ms", 0)} ms'
          + (c("  [降级]", RED) if data.get("degraded") else ""))
    print()
    print(f'{c("小暖>", BOLD)} {r["reply"]}')
    if r.get("tips"):
        print(f'  {c("可以做：", DIM)}' + " / ".join(r["tips"]))
    if r.get("follow_up"):
        print(f'  {c("追问：", DIM)}{r["follow_up"]}')
    print()


def chat_once(base_url: str, text: str, session_id: str = "cli") -> dict:
    with httpx.Client(timeout=config.RPC_TIMEOUT * 2) as client:
        resp = client.post(f"{base_url}/api/chat", json={"text": text, "session_id": session_id})
    resp.raise_for_status()
    return resp.json()


def chat_stream(base_url: str, text: str, session_id: str = "cli") -> dict:
    """SSE 流式：边跑边显示每一步，最后返回完整结果。"""
    final: dict = {}
    with httpx.Client(timeout=config.RPC_TIMEOUT * 2) as client:
        with client.stream("POST", f"{base_url}/api/chat/stream",
                           json={"text": text, "session_id": session_id}) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "stage":
                    print(f'  ├─ {c(event["stage"], DIM)} {event["detail"]} …', flush=True)
                elif etype == "final":
                    final = event["data"]
                elif etype == "error":
                    print(f'  └─ {c("错误", RED)} {event.get("detail")}', flush=True)
    return final


def run_demo(base_url: str, stream: bool = True) -> None:
    print(c("\n===== 前端进程：内置用例 =====", BOLD))
    for i, text in enumerate(DEMO_CASES, 1):
        print(c(f"\n[{i}/{len(DEMO_CASES)}] " + "-" * 56, DIM))
        print(f'{c("你>", BOLD)} {text}')
        started = time.time()
        data = chat_stream(base_url, text, session_id=f"demo-{i}") if stream else chat_once(base_url, text)
        if data:
            render_result(data)
        print(c(f"  （前端侧往返 {int((time.time() - started) * 1000)} ms）", DIM))


def interactive(base_url: str) -> None:
    print(c("\n===== 前端进程：交互模式 =====", BOLD))
    print(c("直接输入中文，回车发送；:q 退出。", DIM))
    session_id = "cli-session"
    while True:
        try:
            text = input(c("\n你> ", CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text in (":q", ":quit", "exit", "quit"):
            break
        if not text:
            continue
        data = chat_stream(base_url, text, session_id=session_id)
        if data:
            render_result(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="前端进程：用户输入")
    parser.add_argument("--base-url", default=config.BACKEND_URL, help="后端地址")
    parser.add_argument("--demo", action="store_true", help="跑内置用例")
    parser.add_argument("--no-stream", action="store_true", help="不用 SSE")
    parser.add_argument("text", nargs="*", help="直接给一句文本")
    args = parser.parse_args(argv)

    from .rpc import healthy

    if not healthy(args.base_url):
        print(c(f"后端没起来：{args.base_url}（先运行 run_all.py 或 docker compose up）", RED))
        return 1

    if args.text:
        data = chat_once(args.base_url, " ".join(args.text))
        print(f'{c("你>", BOLD)} {data["text"]}')
        render_result(data)
    elif args.demo:
        run_demo(args.base_url, stream=not args.no_stream)
    else:
        interactive(args.base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
