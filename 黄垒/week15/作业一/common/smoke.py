"""冒烟测试（两个版本共用）：把「四个进程 + 两张图」的关键行为都跑一遍。

不依赖浏览器，直接打 HTTP，任何一条断言失败就非 0 退出。

    python -m langgraph_version.smoke_test
    python -m agents_version.smoke_test
"""

from __future__ import annotations

import json
import sys
import time

import httpx

from . import config, launch, rpc

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES = {
    "positive": "今天终于把拖了两周的项目交了，组长在会上点名夸了我一句！",
    "negative": "明天要答辩，PPT 还有十页没做完，感觉要完蛋了。",
    "neutral": "刚把杯子放桌上了。",
    "crisis": "最近总觉得活着没什么意思，什么都不想做。",
}

_results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    _results.append((bool(ok), name))
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f"   [{detail}]" if detail else ""), flush=True)


def post(url: str, payload: dict, timeout: float = 60) -> httpx.Response:
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, json=payload)


def section(title: str) -> None:
    print(f"\n{title}\n" + "-" * 62, flush=True)


def run(pkg: str) -> int:
    print("=" * 62)
    print(f"  冒烟测试：{pkg} / 四进程链路")
    print(f"  {config.summary()}")
    print("=" * 62)

    procs = launch.start_all(pkg)
    extra: list = []
    try:
        try:
            rpc.wait_until_healthy(launch.TARGETS, quiet=True)
            check(True, "三个服务全部 /health 通过")
        except rpc.RpcError as exc:
            check(False, "服务启动", str(exc))
            return 1

        section("[进程1] 情感识别 /analyze")
        got = {}
        for name, text in CASES.items():
            resp = post(f"{config.SENTIMENT_URL}/analyze", {"text": text})
            data = resp.json().get("data", {})
            got[name] = data
            expect = {"positive": "positive", "negative": "negative", "neutral": "neutral", "crisis": "negative"}[name]
            check(resp.status_code == 200 and data.get("label") == expect,
                  f"{name}: {text[:16]}… -> {data.get('label')}/{data.get('emotion')}",
                  f"期望 {expect}, 置信 {data.get('confidence')}, {resp.json().get('ms')}ms")
        check(bool(got["positive"].get("notes")), "返回了图内执行轨迹 notes", " | ".join(got["positive"].get("notes") or [])[:90])
        check(bool(got["positive"].get("reason")), "给了判断依据", got["positive"].get("reason", ""))

        section("[进程2] 情绪回应 /respond")
        expect_strategy = [("positive", "encourage"), ("negative", "soothe"), ("neutral", "listen"), ("crisis", "crisis")]
        for name, strategy in expect_strategy:
            resp = post(f"{config.REPLY_URL}/respond", {"text": CASES[name], "sentiment": got[name]})
            data = resp.json().get("data", {})
            check(resp.status_code == 200 and data.get("strategy") == strategy,
                  f"{name} -> 策略 {data.get('strategy')}（{len(str(data.get('reply') or ''))} 字）",
                  f"期望 {strategy}, 来源 {data.get('source')}")
            if name == "negative":
                check(bool(data.get("reply")), "负向回应正文非空", (data.get("reply") or "")[:40] + "…")
                check(any("质检" in n for n in (data.get("notes") or [])), "走过质检节点", " | ".join(data.get("notes") or [])[-80:])

        section("[后端] 全链路 /api/chat")
        for name in ("positive", "negative"):
            resp = post(f"{config.BACKEND_URL}/api/chat", {"text": CASES[name], "session_id": "smoke"})
            body = resp.json()
            steps = body.get("trace") or []
            check(resp.status_code == 200 and body.get("sentiment", {}).get("label") == name,
                  f"{name} 全链路 200 且标签正确",
                  f'{len(steps)} 步 / {body.get("elapsed_ms")}ms / degraded={body.get("degraded")}')
            check(len(steps) >= 4, "链路轨迹 >= 4 步", " → ".join(s.get("node", "") for s in steps))
            check(bool(body.get("reply", {}).get("reply")), "拿到了回应正文", (body.get("reply", {}).get("reply") or "")[:36] + "…")

        section("[后端] SSE 流式 /api/chat/stream")
        stages, final = [], None
        with httpx.Client(timeout=90) as client:
            with client.stream("POST", f"{config.BACKEND_URL}/api/chat/stream",
                               json={"text": CASES["negative"], "session_id": "smoke"}) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        ev = json.loads(line[5:])
                        if ev.get("type") == "stage":
                            stages.append(ev["stage"])
                        elif ev.get("type") == "final":
                            final = ev["data"]
        check(len(stages) >= 4, "SSE 至少推了 4 条阶段事件", " → ".join(stages))
        check(final is not None and final.get("reply", {}).get("reply"), "SSE 结束时带回完整结果")

        section("[健壮性]")
        resp = post(f"{config.BACKEND_URL}/api/chat", {"text": "   "})
        check(resp.status_code == 400, "空输入被后端拒绝（400）", f"实际 {resp.status_code}")

        # 降级：起一个「进程1 指向死端口」的后端实例，验证它不是抛 500，而是 degraded
        degrade_proc = launch.spawn(pkg, "backend", {"BACKEND_PORT": "8199", "SENTIMENT_URL": "http://127.0.0.1:9"})
        extra.append(degrade_proc)
        try:
            rpc.wait_until_healthy({"降级后端": "http://127.0.0.1:8199"}, timeout=30, quiet=True)
            resp = post("http://127.0.0.1:8199/api/chat", {"text": CASES["negative"]})
            body = resp.json()
            check(resp.status_code == 200 and body.get("degraded") is True,
                  "进程1 挂掉时后端降级返回（degraded=True）",
                  f'label={body.get("sentiment", {}).get("label")} 来源={body.get("sentiment", {}).get("source")}')
            check(bool(body.get("reply", {}).get("reply")), "降级后依然有回应正文")
        finally:
            for proc in extra:
                proc.terminate()
    finally:
        launch.stop_all(procs)

    passed = sum(1 for ok, _ in _results if ok)
    total = len(_results)
    print("\n" + "=" * 62)
    print(f"  结果：{passed}/{total} 通过")
    failed = [name for ok, name in _results if not ok]
    if failed:
        print("  失败项：" + "; ".join(failed))
    print("=" * 62, flush=True)
    return 0 if passed == total else 1


def main(pkg: str) -> int:
    started = time.time()
    code = run(pkg)
    print(f"耗时 {time.time() - started:.1f}s")
    return code
