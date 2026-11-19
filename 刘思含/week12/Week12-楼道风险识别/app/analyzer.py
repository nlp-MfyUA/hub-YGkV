"""识别编排：预处理 -> 组装多模态消息 -> 结构化输出 -> 校验 -> 重试。

LangChain 只负责"发请求 + 收结构化结果"，业务校验仍然在这里。
"""

from __future__ import annotations

import base64
import logging
import re
import time

from langchain.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app import image_utils
from app.llm import SCORE_RANGES, STRUCTURED_MODE, build_model
from app.prompt import SYSTEM_PROMPT, USER_PROMPT
from app.schemas import HallwayRisk

LOGGER = logging.getLogger("app.analyzer")

HIGH_KEYWORDS = (
    "电动车",
    "电动自行车",
    "电瓶",
    "电池",
    "飞线",
    "充电",
    "接线板",
    "插线板",
)

BOX_PROMPT = "同时用 0-1 归一化坐标给出隐患物品的外接框。"


class AnalysisError(RuntimeError):
    """模型调用或输出解析失败。"""


def build_messages(img_bytes: bytes, with_boxes: bool = False) -> list:
    """组装多模态消息：图片块在前，文字块在后。"""
    jpeg = image_utils.preprocess(img_bytes)
    uri = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()

    text = USER_PROMPT + ("\n" + BOX_PROMPT if with_boxes else "")
    return [
        SystemMessage(SYSTEM_PROMPT),
        HumanMessage(
            content=[
                {"type": "image_url", "image_url": {"url": uri}},
                {"type": "text", "text": text},
            ]
        ),
    ]


def _check_consistency(r: HallwayRisk) -> None:
    """跨字段校验：模型自己不会保证这些。"""
    if r.risk_level == "non_hallway":
        if r.is_hallway:
            raise ValueError("risk_level 为 non_hallway 但 is_hallway 为真")
        return

    if not r.is_hallway:
        raise ValueError(f"risk_level 为 {r.risk_level} 但 is_hallway 为假")

    if r.risk_level == "high":
        joined = " ".join(r.hazards + r.observations)
        if not any(k in joined for k in HIGH_KEYWORDS):
            raise ValueError("判为高风险但未识别到电动车/电瓶/充电等元素")

    lo, hi = SCORE_RANGES[r.risk_level]
    if not (lo - 10 <= r.risk_score <= hi + 10):
        raise ValueError(f"risk_score={r.risk_score} 与等级 {r.risk_level} 不匹配")


def _structured_runner(provider: str):
    """根据 STRUCTURED_MODE 选择结构化输出方式。"""
    model = build_model(provider)
    if STRUCTURED_MODE == "json":
        return model.with_structured_output(HallwayRisk, method="json_schema")
    return model.with_structured_output(HallwayRisk)  # 默认 ToolStrategy，通用


def analyze(img_bytes: bytes, provider: str) -> tuple[HallwayRisk, int]:
    """返回 (结构化结果, 耗时毫秒)。失败抛 AnalysisError。"""
    runner = _structured_runner(provider)
    messages = build_messages(img_bytes)

    last_err: Exception | None = None
    for attempt in (1, 2):
        t0 = time.perf_counter()
        try:
            result = runner.invoke(messages)
            if not isinstance(result, HallwayRisk):
                result = HallwayRisk.model_validate(result)
            _check_consistency(result)
            latency = int((time.perf_counter() - t0) * 1000)
            return result, latency
        except (ValidationError, ValueError, TypeError) as exc:
            last_err = exc
            LOGGER.warning("第 %d 次输出不合规: %s", attempt, exc)
            if attempt == 1:
                # 把错误信息反馈给模型，再试一次
                messages = messages + [
                    HumanMessage(
                        f"上一次输出不符合要求：{exc}。请严格按规则重新输出，"
                        f"只输出结构化结果字段。"
                    )
                ]
        except Exception as exc:  # noqa: BLE001 - 网络/鉴权/超时
            LOGGER.exception("模型调用失败")
            raise AnalysisError(f"模型调用失败：{exc}") from exc

    raise AnalysisError(f"模型输出两次均不符合要求：{last_err}")


def analyze_with_boxes(img_bytes: bytes, provider: str) -> tuple[HallwayRisk, int, list[list[float]]]:
    """在 analyze 基础上额外解析标注框（可选增强）。"""
    result, latency = analyze(img_bytes, provider)

    # 标注框单独走一次纯文本解析，失败不影响主结果
    boxes: list[list[float]] = []
    try:
        jpeg = image_utils.preprocess(img_bytes)
        uri = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
        model = build_model(provider)
        msg = [
            SystemMessage(
                "你是图像标注助手。只输出 JSON：{\"boxes\": [[x1,y1,x2,y2], ...]}，"
                "坐标为 0-1 归一化值。没有隐患物品时输出 {\"boxes\": []}。"
            ),
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": uri}},
                    {"type": "text", "text": "框出画面中的电动车、电瓶、充电线、可燃堆积物。"},
                ]
            ),
        ]
        text = model.invoke(msg).text
        boxes = _parse_boxes(text)
    except Exception:  # noqa: BLE001
        LOGGER.info("标注框解析失败，跳过")

    return result, latency, boxes


def _parse_boxes(text: str) -> list[list[float]]:
    """从模型输出里抽 boxes 数组，兼容 ```json 包裹。"""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return []
    import json

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    out: list[list[float]] = []
    for box in data.get("boxes", [])[:5]:
        if isinstance(box, (list, tuple)) and len(box) == 4:
            try:
                vals = [max(0.0, min(1.0, float(v))) for v in box]
            except (TypeError, ValueError):
                continue
            if vals[2] > vals[0] and vals[3] > vals[1]:
                out.append(vals)
    return out
