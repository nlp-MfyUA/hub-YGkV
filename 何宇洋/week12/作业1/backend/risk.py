"""将视觉模型给出的可见事实映射为课程定义的五类结果。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    is_corridor: bool | None
    image_quality: Literal["clear", "unclear"]
    electric_bike: bool
    battery: bool
    charging_wire: bool
    fire_or_smoke: bool
    clutter: Literal["none", "minor", "large"]
    blocks_passage: bool
    large_combustibles: bool
    description: str = Field(min_length=1, max_length=1200)
    evidence: list[str] = Field(min_length=1, max_length=10)
    uncertainty: str = Field(max_length=600)


LABELS = {"high": "高风险", "medium": "中风险", "low": "低风险", "none": "无风险", "not_corridor": "非楼道"}
ADVICE = {
    "high": ["联系物业或管理人员核实并处理电动车、电瓶及充电隐患。", "保持疏散通道畅通；如发现烟火，立即远离并联系消防。"],
    "medium": ["优先清理阻塞通道的堆积物。", "将纸箱、木质家具等可燃物移至合规存放地点。"],
    "low": ["及时清理零散堆放物，避免堆积扩大。", "持续保持通道畅通。"],
    "none": ["保持现状，定期巡检；照片判断范围仅限可见区域。"],
    "not_corridor": ["请重新拍摄楼道、走廊或楼梯间，尽量包含完整通行区域。"],
}


def classify(o: Observation) -> dict:
    # 模糊图片不能被误判为安全；不确定状态不属于风险类别。
    if o.image_quality == "unclear" or o.is_corridor is None:
        return {"risk": None, "label": "待复核", "needs_review": True,
                "suggestions": ["请在光线充足处重新拍摄，确保通道和物品清晰可见。"]}
    if not o.is_corridor:
        risk = "not_corridor"
    elif o.electric_bike or o.battery or o.charging_wire or o.fire_or_smoke:
        risk = "high"
    elif o.blocks_passage or o.large_combustibles or o.clutter == "large":
        risk = "medium"
    elif o.clutter == "minor":
        risk = "low"
    else:
        risk = "none"
    return {"risk": risk, "label": LABELS[risk], "needs_review": False, "suggestions": ADVICE[risk]}


def demo_observation(preset: str) -> Observation:
    data = dict(is_corridor=True, image_quality="clear", electric_bike=False,
                battery=False, charging_wire=False, fire_or_smoke=False,
                clutter="none", blocks_passage=False, large_combustibles=False,
                description="演示场景：楼道整洁，通行区域没有堆物。",
                evidence=["固定示例：通行区域无堆物"], uncertainty="模拟结果未分析上传图片，不能用于判断照片内容。")
    if preset == "high":
        data.update(electric_bike=True, description="演示场景：楼道内停放电动车。", evidence=["固定示例：楼道内有电动车"])
    elif preset == "medium":
        data.update(clutter="large", blocks_passage=True, large_combustibles=True,
                    description="演示场景：大量纸箱与木家具堵塞楼道。", evidence=["固定示例：大量可燃堆积物影响通行"])
    elif preset == "low":
        data.update(clutter="minor", description="演示场景：楼道边缘有少量堆物。", evidence=["固定示例：少量杂物，未严重阻塞"])
    elif preset == "not_corridor":
        data.update(is_corridor=False, description="演示场景：图片为室外风景。", evidence=["固定示例：与楼道无关"])
    return Observation.model_validate(data)
