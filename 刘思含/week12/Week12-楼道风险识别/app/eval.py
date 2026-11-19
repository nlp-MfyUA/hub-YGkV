"""批量评测。

目录结构（按真实类别分文件夹）:
    data/eval/high/*.jpg
    data/eval/medium/*.jpg
    data/eval/low/*.jpg
    data/eval/none/*.jpg
    data/eval/non_hallway/*.jpg

用法:
    python -m app.eval                 # 用默认 provider
    python -m app.eval qwen            # 指定 provider
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.analyzer import AnalysisError, analyze  # noqa: E402
from app.llm import DEFAULT_PROVIDER  # noqa: E402

EVAL_DIR = Path("data/eval")
LABELS = ["none", "low", "medium", "high", "non_hallway"]
EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> int:
    provider = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROVIDER

    if not EVAL_DIR.exists():
        print(f"评测目录不存在: {EVAL_DIR.resolve()}")
        print("请按 high/medium/low/none/non_hallway 分文件夹放图片")
        return 2

    rows: list[tuple[str, str, int]] = []  # (真实, 预测, 耗时)
    grouped = any((EVAL_DIR / g).is_dir() for g in LABELS)
    if grouped:
        samples = [
            (p, gt)
            for gt in LABELS
            for p in sorted((EVAL_DIR / gt).glob("*"))
            if p.suffix.lower() in EXTS
        ]
    else:
        samples = [
            (p, p.parent.name)
            for p in sorted(EVAL_DIR.rglob("*"))
            if p.suffix.lower() in EXTS
        ]

    if not samples:
        print("没有找到评测图片")
        return 2

    print(f"provider={provider}  样本数={len(samples)}\n")

    for path, gt in samples:
        try:
            result, latency = analyze(path.read_bytes(), provider)
            pred = result.risk_level
            mark = "√" if pred == gt else "×"
            print(f"{mark} {path.name[:36]:<38} 真实={gt:<12} 预测={pred:<12} {latency}ms")
        except AnalysisError as exc:
            pred = "error"
            latency = 0
            print(f"✖ {path.name[:36]:<38} 真实={gt:<12} 失败: {exc}")
        rows.append((gt, pred, latency))

    # ---- 指标 ----
    total = len(rows)
    correct = sum(1 for g, p, _ in rows if g == p)
    acc = correct / total if total else 0
    avg_ms = sum(r[2] for r in rows) / total if total else 0

    print("\n" + "=" * 60)
    print(f"准确率 {acc:.1%}  ({correct}/{total})   平均耗时 {avg_ms:.0f} ms")
    print("=" * 60)

    print("\n混淆矩阵（行=真实，列=预测）")
    header = "真实\\预测".ljust(12) + "".join(c.ljust(12) for c in LABELS)
    print(header)
    for gt in LABELS:
        line = gt.ljust(12)
        for pred in LABELS:
            n = sum(1 for g, p, _ in rows if g == gt and p == pred)
            line += str(n if n else ".").ljust(12)
        print(line)

    # ---- 高风险漏判：最严重的问题 ----
    missed_high = [
        p for g, p, _ in rows if g == "high" and p != "high"
    ]
    if missed_high:
        print(f"\n⚠ 高风险漏判 {len(missed_high)} 张: {Counter(missed_high)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
