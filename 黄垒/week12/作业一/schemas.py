"""接口的请求 / 响应数据结构（Pydantic 负责校验和 OpenAPI 文档）。"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    """五档判定结果"""

    SAFE = "无风险"
    LOW = "低风险"
    MEDIUM = "中风险"
    HIGH = "高风险"
    NOT_CORRIDOR = "非楼道"


# 等级 -> 分数区间，用于把模型的「等级」和「分数」两个输出校准成一致
SCORE_RANGE: dict[RiskLevel, tuple[int, int]] = {
    RiskLevel.SAFE: (0, 10),
    RiskLevel.LOW: (11, 40),
    RiskLevel.MEDIUM: (41, 70),
    RiskLevel.HIGH: (71, 100),
    RiskLevel.NOT_CORRIDOR: (0, 0),
}

# 模型常见的同义说法，统一映射到枚举值
LEVEL_ALIASES: dict[str, RiskLevel] = {
    "无隐患": RiskLevel.SAFE,
    "无风险": RiskLevel.SAFE,
    "安全": RiskLevel.SAFE,
    "低风险": RiskLevel.LOW,
    "低": RiskLevel.LOW,
    "中等风险": RiskLevel.MEDIUM,
    "中风险": RiskLevel.MEDIUM,
    "中": RiskLevel.MEDIUM,
    "高风险": RiskLevel.HIGH,
    "高": RiskLevel.HIGH,
    "非楼道": RiskLevel.NOT_CORRIDOR,
    "不是楼道": RiskLevel.NOT_CORRIDOR,
    "无关图片": RiskLevel.NOT_CORRIDOR,
    # 英文模型有时不按中文枚举输出
    "safe": RiskLevel.SAFE,
    "none": RiskLevel.SAFE,
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "moderate": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "not corridor": RiskLevel.NOT_CORRIDOR,
    "not_corridor": RiskLevel.NOT_CORRIDOR,
    "non-corridor": RiskLevel.NOT_CORRIDOR,
}

SEVERITY_ALIASES = {
    "low": "low",
    "低": "low",
    "轻微": "low",
    "medium": "medium",
    "中": "medium",
    "中等": "medium",
    "high": "high",
    "高": "high",
    "严重": "high",
}


class Finding(BaseModel):
    """一条隐患证据。"""

    category: str = Field(default="其它", description="隐患类别，如电动车、飞线充电、堆积物")
    description: str = Field(default="", description="在图片里看到的客观依据")
    severity: Literal["low", "medium", "high"] = "low"


class RiskAssessment(BaseModel):
    """模型输出的结构化判定结果。"""

    is_corridor: bool = Field(description="是否拍摄于居民楼楼道 / 楼梯间 / 疏散通道")
    scene: str = Field(default="", description="对画面场景的一句话描述")
    risk_level: RiskLevel
    risk_score: int = Field(default=0, ge=0, le=100, description="0-100，分数越高越危险")
    summary: str = Field(default="", description="一句话结论")
    findings: list[Finding] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0, le=1)
    need_human_review: bool = False

    @field_validator("findings", mode="before")
    @classmethod
    def _coerce_findings(cls, value):
        """模型偶尔把 findings 写成字符串数组，这里统一成 Finding。"""
        if value is None:
            return []
        if isinstance(value, (str, dict)):
            value = [value]
        if not isinstance(value, list):
            return []
        normalized = []
        for item in value:
            if isinstance(item, str):
                normalized.append({"category": "其它", "description": item, "severity": "low"})
            elif isinstance(item, dict):
                severity = str(item.get("severity", "low")).strip().lower()
                normalized.append(
                    {
                        "category": str(item.get("category") or item.get("type") or "其它"),
                        "description": str(item.get("description") or item.get("detail") or ""),
                        "severity": SEVERITY_ALIASES.get(severity, "low"),
                    }
                )
        return normalized

    @field_validator("suggestions", mode="before")
    @classmethod
    def _coerce_suggestions(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]


class AnalysisMeta(BaseModel):
    model: str
    provider: str
    latency_ms: int
    image_bytes: int
    image_size: str
    timestamp: str
    request_id: str


class AnalysisResponse(BaseModel):
    ok: bool = True
    data: RiskAssessment
    meta: AnalysisMeta


class HealthResponse(BaseModel):
    ok: bool
    model: str
    provider: str
    max_upload_mb: int
