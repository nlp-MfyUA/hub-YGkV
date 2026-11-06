"""评测指标计算（技术设计文档 §9.2）。

指标：总体准确率、5×5 混淆矩阵、各类 precision / recall / F1、
高风险召回率单独突出（漏报代价最大）、平均 / P95 延迟、解析失败率。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.schemas import RISK_LEVELS

LABELS = list(RISK_LEVELS)


@dataclass
class EvalOutcome:
    """单条样本的评测结果。status ∈ ok / parse_fail / error。"""

    filename: str
    true_label: str
    predicted: str | None = None
    arbiter_override: bool = False
    latency_ms: int = 0
    status: str = "ok"
    error: str = ""
    evidence: str = ""


@dataclass
class Metrics:
    total: int = 0
    correct: int = 0
    parse_fail: int = 0
    latencies: list[int] = field(default_factory=list)
    confusion: dict[str, dict[str, int]] = field(
        default_factory=lambda: {t: {p: 0 for p in LABELS} for t in LABELS}
    )

    @property
    def accuracy(self) -> float:
        ok = self.total - self.parse_fail
        return self.correct / ok if ok else 0.0

    @property
    def parse_fail_rate(self) -> float:
        return self.parse_fail / self.total if self.total else 0.0

    @property
    def avg_latency_ms(self) -> int:
        return int(sum(self.latencies) / len(self.latencies)) if self.latencies else 0

    @property
    def p95_latency_ms(self) -> int:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[max(0, math.ceil(0.95 * len(s)) - 1)]

    def per_class(self) -> list[dict[str, float | int | str]]:
        """按类别计算 P / R / F1 / support。"""
        rows: list[dict[str, float | int | str]] = []
        for label in LABELS:
            tp = self.confusion[label][label]
            fp = sum(self.confusion[t][label] for t in LABELS) - tp
            fn = sum(self.confusion[label].values()) - tp
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            rows.append({
                "label": label,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": tp + fn,
            })
        return rows

    def high_risk_recall(self) -> tuple[float, int, int]:
        """高风险召回率单独返回（漏报高风险代价最大）。"""
        tp = self.confusion["高风险"]["高风险"]
        fn = sum(self.confusion["高风险"].values()) - tp
        return (tp / (tp + fn) if tp + fn else 0.0), tp, tp + fn


def compute_metrics(outcomes: list[EvalOutcome]) -> Metrics:
    m = Metrics(total=len(outcomes))
    for o in outcomes:
        if o.status != "ok" or o.predicted is None:
            m.parse_fail += 1
            continue
        if o.latency_ms:
            m.latencies.append(o.latency_ms)
        if o.true_label in m.confusion and o.predicted in LABELS:
            m.confusion[o.true_label][o.predicted] += 1
        if o.predicted == o.true_label:
            m.correct += 1
    return m


def build_report(outcomes: list[EvalOutcome], *, dataset: str, provider: str,
                 model: str) -> str:
    """生成 Markdown 评测报告。"""
    m = compute_metrics(outcomes)
    lines: list[str] = []
    ap = lines.append

    ap("# 楼道消防风险识别评测报告\n")
    ap(f"- 数据集：`{dataset}`（{m.total} 条）")
    ap(f"- Provider / Model：`{provider}` / `{model}`")
    ap(f"- 生成时间：{_now()}\n")

    ap("## 总体指标\n")
    ap(f"- 总体准确率：**{m.accuracy:.1%}**（{m.correct}/{m.total - m.parse_fail}）")
    hr, hr_tp, hr_all = m.high_risk_recall()
    ap(f"- **高风险召回率：{hr:.1%}（{hr_tp}/{hr_all}）** ← 漏报高风险代价最大，重点盯防")
    ap(f"- 解析失败率：{m.parse_fail_rate:.1%}（{m.parse_fail}/{m.total}）")
    ap(f"- 平均延迟：{m.avg_latency_ms} ms")
    ap(f"- P95 延迟：{m.p95_latency_ms} ms\n")

    ap("## 混淆矩阵（行 = 真实标签，列 = 预测标签）\n")
    ap("| 真实 \\ 预测 | " + " | ".join(LABELS) + " |")
    ap("|" + "---|" * (len(LABELS) + 1))
    for t in LABELS:
        ap(f"| **{t}** | " + " | ".join(str(m.confusion[t][p]) for p in LABELS) + " |")
    ap("")

    ap("## 各类 precision / recall / F1\n")
    ap("| 类别 | precision | recall | F1 | support |")
    ap("|---|---|---|---|---|")
    for row in m.per_class():
        ap(f"| {row['label']} | {row['precision']:.2f} | {row['recall']:.2f} "
           f"| {row['f1']:.2f} | {row['support']} |")
    ap("")

    errors = [o for o in outcomes if o.status != "ok" or o.predicted != o.true_label]
    ap(f"## 错误样本清单（{len(errors)} 条）\n")
    if not errors:
        ap("无错误样本。\n")
    else:
        ap("| 文件 | 真实 | 预测 | 判定依据（摘要） |")
        ap("|---|---|---|---|")
        for o in errors:
            pred = o.predicted or f"解析失败（{o.error[:30]}）"
            ap(f"| {o.filename} | {o.true_label} | {pred} | {_escape(o.evidence)[:40]} |")
        ap("")

    return "\n".join(lines)


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")
