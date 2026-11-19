"""数据模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HallwayRisk(BaseModel):
    """模型结构化输出。字段顺序会影响模型生成顺序：先观察，后判断。"""

    is_hallway: bool = Field(description="画面是否是楼道、楼梯间、走廊或公共通行通道")
    observations: list[str] = Field(
        description="观察到的内容：通道宽度、堆物类型与数量、是否有电动元素"
    )
    hazards: list[str] = Field(
        description="命中的隐患元素，例如 电动自行车 / 电瓶 / 飞线充电 / 纸箱堆，无则为空列表"
    )
    risk_level: Literal["none", "low", "medium", "high", "non_hallway"] = Field(
        description="风险等级枚举"
    )
    risk_score: int = Field(ge=0, le=100, description="0-100，与等级对应")
    reason: str = Field(description="2-3 句判定依据")
    advice: list[str] = Field(description="整改建议，可为空列表")


class AnalyzeResponse(BaseModel):
    """返回给前端的结构。"""

    status: Literal["ok", "invalid_output", "error"] = "ok"
    request_id: str
    provider: str
    model: str
    latency_ms: int

    risk_level: str | None = None
    risk_level_cn: str | None = None
    risk_color: str | None = None
    risk_score: int | None = None
    is_hallway: bool | None = None
    hazards: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    reason: str | None = None
    advice: list[str] = Field(default_factory=list)
    need_review: bool = False

    image_url: str | None = None
    annotated_url: str | None = None
    raw_text: str | None = None
    message: str | None = None
