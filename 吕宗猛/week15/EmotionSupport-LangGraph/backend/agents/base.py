"""Agent 公共设施：模型客户端、JSON 解析与离线模拟。"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_openai import ChatOpenAI

import config
from schemas import EmotionResult

# 离线模式使用的轻量情绪词典。不是模型能力，只用于无网关时演示链路。
POSITIVE_WORDS = [
    "开心", "高兴", "快乐", "兴奋", "满足", "幸福", "期待", "希望", "升职", "加薪",
    "成功", "通过", "录取", "喜欢", "热爱", "感动", "温暖", "轻松", "放松", "自豪",
    "顺利", "惊喜", "幸运", "值得", "进步", "被夸", "好评", "胜利", "赢了", "完成",
]

NEGATIVE_WORDS = [
    "难过", "伤心", "焦虑", "压力", "累", "疲惫", "烦", "生气", "愤怒", "委屈",
    "孤独", "失落", "沮丧", "崩溃", "害怕", "担心", "紧张", "自责", "内疚", "后悔",
    "失望", "痛苦", "无助", "迷茫", "失眠", "失败", "被骂", "吵架", "分手", "失业",
    "来不及", "做不好", "没意义", "受不了", "喘不过气",
]


def build_model(model_name: str, temperature: float | None = None) -> ChatOpenAI:
    """构造指向 OpenAI 兼容网关的 LangChain ChatModel。"""
    return ChatOpenAI(
        model=model_name,
        base_url=config.BASE_URL,
        api_key=config.API_KEY or "EMPTY",
        temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
        timeout=config.LLM_TIMEOUT_SECONDS,
        max_retries=1,
    )


def _coerce_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "positive": "positive",
        "正向": "positive",
        "积极": "positive",
        "negative": "negative",
        "负向": "negative",
        "负面": "negative",
        "消极": "negative",
        "neutral": "neutral",
        "中性": "neutral",
        "平静": "neutral",
    }
    return mapping.get(text, "neutral")


def parse_emotion(raw: str) -> EmotionResult:
    """把模型输出解析成 EmotionResult；兼容代码块、前后缀说明与字段缺省。"""
    text = (raw or "").strip()
    text = re.sub(r"^\x60\x60\x60(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\x60\x60\x60$", "", text)

    candidates: list[str] = [text]
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        confidence = data.get("confidence", 0.5)
        intensity = data.get("intensity", 3)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5
        try:
            intensity = max(1, min(5, int(float(intensity))))
        except (TypeError, ValueError):
            intensity = 3
        keywords = data.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, list):
            keywords = []
        return EmotionResult(
            label=_coerce_label(data.get("label")),
            confidence=confidence,
            intensity=intensity,
            reason=str(data.get("reason", "") or "")[:120],
            keywords=[str(item)[:20] for item in keywords[:6]],
        )

    lowered = text.lower()
    if any(word in lowered for word in ("positive", "正向", "积极", "开心")):
        return EmotionResult(label="positive", confidence=0.6, intensity=3,
                             reason="模型以文本形式返回了正向判断", keywords=[])
    if any(word in lowered for word in ("negative", "负向", "负面", "消极")):
        return EmotionResult(label="negative", confidence=0.6, intensity=3,
                             reason="模型以文本形式返回了负向判断", keywords=[])
    return EmotionResult(label="neutral", confidence=0.3, intensity=2,
                         reason="未能解析结构化结果，按中性处理", keywords=[])


def mock_analyze(text: str) -> EmotionResult:
    """离线演示用的规则版情感识别。"""
    content = text or ""
    positive_hits = [word for word in POSITIVE_WORDS if word in content]
    negative_hits = [word for word in NEGATIVE_WORDS if word in content]

    # 处理“不开心”“没意思”这类简单否定：把对应的正向词计为负向
    for word in list(positive_hits):
        if ("不" + word) in content or ("没" + word) in content:
            positive_hits.remove(word)
            negative_hits.append("不" + word)

    pos_count, neg_count = len(positive_hits), len(negative_hits)
    if pos_count == 0 and neg_count == 0:
        return EmotionResult(
            label="neutral", confidence=0.55, intensity=2,
            reason="没有检测到明显的情绪词，先按中性理解",
            keywords=[],
        )

    if pos_count > neg_count:
        label = "positive"
        keywords = positive_hits
    elif neg_count > pos_count:
        label = "negative"
        keywords = negative_hits
    else:
        # 正负同时出现时，优先照顾负面情绪（更需要被接住）
        label = "negative"
        keywords = negative_hits + positive_hits

    top_hits = max(pos_count, neg_count)
    confidence = min(0.96, 0.58 + 0.08 * top_hits)
    intensity = max(1, min(5, 2 + top_hits))
    hint = "、".join(dict.fromkeys(keywords))[:60]
    return EmotionResult(
        label=label,
        confidence=round(confidence, 2),
        intensity=intensity,
        reason=("检测到情绪线索：" + hint) if hint else "检测到一定的情绪波动",
        keywords=list(dict.fromkeys(keywords))[:6],
    )


def _clip(text: str, limit: int = 46) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= limit else compact[:limit] + "…"


def mock_reply(agent_key: str, text: str, emotion: EmotionResult) -> str:
    """离线演示用的回应模板，保持三个 Agent 的角色差异。"""
    snippet = _clip(text)
    if agent_key == "encourage":
        return (
            f"你愿意把「{snippet}」说出来，我能感到这里面有一股亮堂堂的力量。\n\n"
            "这份开心不是小事。它说明你在意、你投入过，也说明有些努力正在被看见。"
            "先别急着把它收起来，允许自己多停留一会儿。\n\n"
            "如果愿意，可以把这个瞬间记下来：当时发生了什么、谁在场、你身体里的感觉是什么样的。"
            "以后低落的时候，它会是一份属于你的证据。"
        )
    if agent_key == "comfort":
        return (
            f"听起来，「{snippet}」让你心里压着一块石头。先不用逼自己马上振作，"
            "难受本身就在提醒你：这段时间你扛得有点多。\n\n"
            "可以试着先做一件很小的事：把呼吸放慢，吸气 4 秒、停 2 秒、呼气 6 秒，重复五轮。"
            "不用解决所有问题，只要让身体先松一点点。\n\n"
            "你不需要一个人把所有情绪都消化完。我在这里，我们可以从最小的那一步开始。"
        )
    return (
        f"我在。关于「{snippet}」，听起来它还在你心里慢慢发酵。\n\n"
        "有时候不急着给事情下结论，先看看它落在身体里的感觉，反而更接近自己。\n\n"
        "如果愿意，可以从一个细节说起：这件事发生时，你最先注意到的是什么？"
        "是胸口紧了一下，还是脑子里反复出现某句话？"
    )
