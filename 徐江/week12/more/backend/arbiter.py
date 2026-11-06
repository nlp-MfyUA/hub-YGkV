"""裁决器：服务端二次裁决（功能设计文档 F-08，技术设计文档 §6）。

规则：
1. scene_type == non_corridor → 直接"非楼道"，忽略 signals；
2. signals 为空/缺失 → 信任模型自报等级，override=False；
3. 否则按 高=3 中=2 低=1 无=0 取 max(weight) 重算；
4. 重算结果 ≠ 自报 → 以服务端为准，override=True（调用方记日志）。
"""
from __future__ import annotations

from .schemas import ModelOutput, RiskLevel

WEIGHT: dict[str, int] = {"高风险": 3, "中风险": 2, "低风险": 1, "无风险": 0}
BY_WEIGHT: dict[int, str] = {v: k for k, v in WEIGHT.items()}


def arbitrate(model_out: ModelOutput) -> tuple[RiskLevel, bool]:
    """返回 (最终等级, 是否发生服务端覆盖)。"""
    if model_out.scene_type == "non_corridor":
        return "非楼道", model_out.risk_level != "非楼道"

    if not model_out.signals:
        return model_out.risk_level, False

    weights = [WEIGHT[s.level] for s in model_out.signals if s.level in WEIGHT]
    if not weights:
        return model_out.risk_level, False

    final = BY_WEIGHT[max(weights)]
    return final, final != model_out.risk_level  # type: ignore[return-value]
