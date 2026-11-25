"""离线演示使用固定词表与回应模板。"""

from __future__ import annotations

import json
import re

from common.schemas import SentimentResult, SentimentType

_POSITIVE_KEYWORDS = (
    "开心", "高兴", "快乐", "兴奋", "激动", "满意", "棒", "太好了", "顺利",
    "成功", "通过", "拿到了", "涨薪", "表扬", "喜欢", "幸福", "期待", "感谢",
    "治愈", "加油", "很赞", "优秀", "惊喜", "舒服", "轻松",
    "happy", "great", "awesome", "good", "excited", "love", "passed", "win",
)

_NEGATIVE_KEYWORDS = (
    "难过", "伤心", "沮丧", "焦虑", "崩溃", "失败", "搞砸", "烦躁", "痛苦",
    "委屈", "压力", "累", "疲惫", "绝望", "担心", "害怕", "生气", "郁闷",
    "失眠", "迷茫", "讨厌", "糟糕", "惨", "哭", "孤独", "无助", "被骂",
    "sad", "bad", "terrible", "anxious", "angry", "failed", "tired", "upset", "stress",
)

_NEGATED_WORD = re.compile(r"不(开心|高兴|顺利|舒服|满意|难过|焦虑|担心|害怕)")


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> set[str]:
    english_words = set(re.findall(r"[a-z]+", text))
    return {word for word in keywords if (word in english_words if word.isascii() else word in text)}


def analyze_sentiment_rule(text: str) -> SentimentResult:
    lowered = text.lower()
    negated = _NEGATED_WORD.findall(lowered)
    remaining = _NEGATED_WORD.sub(" ", lowered)
    positive = _keyword_hits(remaining, _POSITIVE_KEYWORDS)
    negative = _keyword_hits(remaining, _NEGATIVE_KEYWORDS)
    positive.update(f"不{word}" for word in negated if word in _NEGATIVE_KEYWORDS)
    negative.update(f"不{word}" for word in negated if word in _POSITIVE_KEYWORDS)

    if negative and len(negative) >= len(positive):
        sentiment, matched = "negative", negative
    elif positive:
        sentiment, matched = "positive", positive
    else:
        return SentimentResult(
            sentiment="positive", confidence=0.5,
            reason="离线词表未命中，按二分类演示约定走鼓励分支。",
        )

    score = min(0.95, 0.6 + 0.08 * abs(len(positive) - len(negative)))
    return SentimentResult(
        sentiment=sentiment,
        confidence=round(score, 2),
        reason=f"离线词表命中：{'、'.join(sorted(matched)[:3])}。",
    )


def generate_reply_rule(sentiment: SentimentType) -> str:
    if sentiment == "positive":
        return "谢谢你分享这一刻。如果有值得肯定的小进展，可以花一点时间记下来，给自己一点鼓励。"
    return "听起来这件事让你有些不好受，先给自己一点缓冲的时间。等你准备好了，可以先想想眼下哪一件小事是你能处理的。"


def extract_json_dict(raw: str) -> dict:
    """接受完整 JSON 对象，也兼容单层 Markdown 代码围栏。"""
    cleaned = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    value = json.loads(fenced.group(1) if fenced else cleaned)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value
