"""数据模型：五级枚举 / 信号 / 模型输出 / API 响应（技术设计文档 §5）。

枚举值同时是 Prompt 的契约：模型必须从这些值里选，越界即解析失败。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["高风险", "中风险", "低风险", "无风险", "非楼道"]
SceneType = Literal["stairwell", "corridor", "elevator", "garage_passage", "non_corridor"]
Confidence = Literal["high", "medium", "low"]

#: 等级权重（裁决器与 Prompt 冲突规则共用；非楼道不参与比较）
RISK_LEVELS: tuple[str, ...] = ("高风险", "中风险", "低风险", "无风险", "非楼道")
SCENE_TYPES: tuple[str, ...] = (
    "stairwell", "corridor", "elevator", "garage_passage", "non_corridor",
)


class Signal(BaseModel):
    """模型识别出的单条风险信号。"""

    type: str = Field(description="信号类型，如 电动车 / 飞线充电 / 大量堆积物")
    level: RiskLevel = Field(description="该信号对应的等级")
    detail: str = Field(default="", description="可观察细节，引用画面线索")


class ModelOutput(BaseModel):
    """对模型原始 JSON 的结构化校验（解析失败即 502）。"""

    scene_type: SceneType
    risk_level: RiskLevel
    confidence: Confidence
    evidence: str = Field(default="", max_length=400)
    signals: list[Signal] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    """POST /api/analyze 成功响应（技术设计文档 §4.1）。"""

    request_id: str
    risk_level: RiskLevel
    confidence: Confidence
    evidence: str
    scene_type: SceneType
    signals: list[Signal]
    arbiter_override: bool
    provider: str
    model: str
    latency_ms: int


class ErrorResponse(BaseModel):
    """统一错误响应：request_id + 机器可读 error_code + 中文 detail。"""

    request_id: str
    error_code: str
    detail: str


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    base_url_configured: bool
    api_key_configured: bool


class ConfigResponse(BaseModel):
    provider: str
    model: str
    max_image_mb: int
    timeout_s: float
