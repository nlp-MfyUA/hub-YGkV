"""多模态大模型调用层。

职责单一：
    1. 从环境变量读模型配置（默认 DeepSeek，可换成 Qwen-VL / GLM-4V）；
    2. 把图片编码成 data URL，按 OpenAI 兼容协议发起视觉请求；
    3. 对输出做「解析 -> 规范化 -> Pydantic 校验 -> 一次性修复」，
       保证上层拿到的永远是结构稳定的 RiskAssessment。

之所以要把规范化做厚：视觉模型（尤其是带推理过程的模型）会输出
「中等风险」「无隐患」这类同义说法，或者把 findings 写成字符串数组。
这类偏差不应该让整个接口 500，而应在边界层收敛掉。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Any

from openai import APITimeoutError, OpenAI, RateLimitError

from prompts import REPAIR_PROMPT, SYSTEM_PROMPT, USER_PROMPT
from schemas import (
    LEVEL_ALIASES,
    SCORE_RANGE,
    RiskAssessment,
    RiskLevel,
)

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


class VisionError(RuntimeError):
    """模型调用或结果解析失败。"""


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠出第一个 JSON 对象。"""
    raw = (text or "").strip()
    fence = _FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"输出里没有 JSON 对象：{text[:200]!r}")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层不是对象")
    return data


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "是", "楼道", "有", "存在"}:
        return True
    if text in {"false", "no", "0", "否", "非楼道", "无", "不存在"}:
        return False
    return default


def _as_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        text = str(value).strip()
        if text.endswith("%"):
            number = float(text[:-1]) / 100
        else:
            number = float(text)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """把模型的自由输出收敛成 RiskAssessment 能接受的字段。"""
    data = dict(raw)

    # 少数模型会把结果再包一层 {"data": {...}} / {"result": {...}}
    for key in ("data", "result", "assessment"):
        inner = data.get(key)
        if isinstance(inner, dict) and not {"risk_level", "is_corridor"} & data.keys():
            data = dict(inner)
            break

    is_corridor = _as_bool(data.get("is_corridor", data.get("isCorridor")), default=True)

    level_raw = str(data.get("risk_level") or data.get("level") or "").strip()
    level = LEVEL_ALIASES.get(level_raw) or LEVEL_ALIASES.get(level_raw.lower())
    if level is None:
        level = LEVEL_ALIASES.get(level_raw.replace(" ", "").lower())

    score = data.get("risk_score", data.get("score"))
    try:
        score = int(round(float(score)))
    except (TypeError, ValueError):
        score = None

    # 场景判定和等级判定互相纠偏：这两个字段不能自相矛盾
    if not is_corridor:
        level = RiskLevel.NOT_CORRIDOR
    elif level == RiskLevel.NOT_CORRIDOR:
        is_corridor = False

    if level is None:
        # 没有给出合法等级时，用分数反推
        if score is None:
            level = RiskLevel.MEDIUM if is_corridor else RiskLevel.NOT_CORRIDOR
        elif score >= 71:
            level = RiskLevel.HIGH
        elif score >= 41:
            level = RiskLevel.MEDIUM
        elif score >= 11:
            level = RiskLevel.LOW
        else:
            level = RiskLevel.SAFE

    low, high = SCORE_RANGE[level]
    if score is None:
        score = (low + high) // 2
    score = max(low, min(high, score))

    findings = data.get("findings", data.get("hazards", []))
    suggestions = data.get("suggestions", data.get("advice", []))

    scene = str(data.get("scene") or data.get("description") or "").strip()
    summary = str(data.get("summary") or data.get("reason") or data.get("conclusion") or "").strip()
    if not summary:
        summary = "；".join(
            item.get("description", "")
            for item in findings
            if isinstance(item, dict) and item.get("description")
        ) or f"判定为{level.value}。"

    confidence = _as_float(data.get("confidence"), 0.7, 0.0, 1.0)
    need_review = _as_bool(data.get("need_human_review", data.get("needHumanReview")), default=False)

    # 没有给出建议时，按等级补一条兜底建议，前端永远有内容可展示
    if not suggestions:
        suggestions = {
            RiskLevel.HIGH: ["立即清理电动车 / 电瓶并停止充电，必要时联系物业和消防部门处理。"],
            RiskLevel.MEDIUM: ["尽快清走纸箱、木质家具等可燃堆积物，恢复通道宽度。"],
            RiskLevel.LOW: ["清理少量堆物，保持疏散通道整洁畅通。"],
            RiskLevel.SAFE: ["现场状态良好，保持通道畅通，定期巡查。"],
            RiskLevel.NOT_CORRIDOR: [],
        }[level]

    return {
        "is_corridor": is_corridor,
        "scene": scene,
        "risk_level": level.value,
        "risk_score": score,
        "summary": summary,
        "findings": findings,
        "suggestions": suggestions,
        "confidence": round(confidence, 2),
        "need_human_review": need_review,
    }


class VisionClient:
    def __init__(self) -> None:
        self.api_key = _env("VISION_API_KEY") or _env("LLM_API_KEY")
        if not self.api_key:
            raise VisionError(
                "缺少 VISION_API_KEY / LLM_API_KEY，请把 .env.example 复制为 .env 并填入 Key。"
            )

        self.base_url = _env("VISION_BASE_URL") or _env("LLM_BASE_URL") or "https://api.deepseek.com"
        self.model = _env("VISION_MODEL") or _env("LLM_MODEL") or "deepseek-flash"
        self.provider = _env("VISION_PROVIDER") or _guess_provider(self.base_url)
        self.max_tokens = int(_env("VISION_MAX_TOKENS", "3000"))
        self.timeout = float(_env("VISION_TIMEOUT", "150"))
        self.max_retries = int(_env("VISION_MAX_RETRIES", "3"))

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    # ------------------------------------------------------------------ #
    # 对外
    # ------------------------------------------------------------------ #
    def analyze(self, image_bytes: bytes, mime: str = "image/jpeg") -> tuple[RiskAssessment, int]:
        """识别一张图片，返回 (结构化结果, 重试次数)。"""
        start = time.perf_counter()
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"

        raw_text = self._chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": USER_PROMPT},
                    ],
                },
            ]
        )

        try:
            assessment = RiskAssessment.model_validate(normalize(_extract_json(raw_text)))
            return assessment, 0
        except Exception as exc:  # JSON 坏了或字段不合法 -> 带着报错让模型重答一次
            logger.warning("首次输出解析失败，触发修复：%s", exc)
            repair_text = self._chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {
                                "type": "text",
                                "text": USER_PROMPT
                                + "\n\n"
                                + REPAIR_PROMPT.format(error=str(exc)[:500], raw=raw_text[:1500]),
                            },
                        ],
                    },
                ]
            )
            try:
                assessment = RiskAssessment.model_validate(normalize(_extract_json(repair_text)))
                return assessment, 1
            except Exception as repair_exc:
                raise VisionError(f"模型输出无法解析：{repair_exc}；原始输出：{raw_text[:300]}") from repair_exc

    # ------------------------------------------------------------------ #
    # 底层
    # ------------------------------------------------------------------ #
    def _chat(self, messages: list[dict[str, Any]]) -> str:
        # DeepSeek / Qwen 的兼容接口都支持 JSON 模式；遇到不支持时自动降级
        json_mode = _env("VISION_JSON_MODE", "true").lower() != "false"
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": 0.1,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            try:
                response = self.client.chat.completions.create(**kwargs)
                content = (response.choices[0].message.content or "").strip()
                if not content:
                    raise VisionError("模型返回了空内容（可能 max_tokens 被推理过程耗尽）")
                return content
            except RateLimitError as exc:
                last_error = exc
                time.sleep(min(2**attempt, 10))
            except APITimeoutError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(2)
            except VisionError:
                raise
            except Exception as exc:  # 网络抖动、5xx、response_format 不支持
                last_error = exc
                message = str(exc).lower()
                if json_mode and ("response_format" in message or "json_object" in message):
                    logger.warning("当前模型不支持 JSON 模式，降级为普通输出")
                    json_mode = False
                    continue
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 8))

        raise VisionError(f"视觉模型调用失败（已尝试 {self.max_retries} 次）：{last_error}")


def _guess_provider(base_url: str) -> str:
    host = base_url.lower()
    if "deepseek" in host:
        return "DeepSeek"
    if "dashscope" in host or "aliyun" in host:
        return "阿里云百炼"
    if "bigmodel" in host:
        return "智谱"
    if "openai" in host:
        return "OpenAI"
    return host or "自定义"


def describe_error(exc: Exception) -> str:
    """把底层异常翻译成用户能看懂的一句话。"""
    text = str(exc)
    if "401" in text or "authentication" in text.lower():
        return "模型鉴权失败，请检查 .env 里的 API Key。"
    if "429" in text:
        return "模型调用频率或额度受限，请稍后再试。"
    if "timeout" in text.lower():
        return "模型响应超时，请重试或换一张更小的图片。"
    return text
