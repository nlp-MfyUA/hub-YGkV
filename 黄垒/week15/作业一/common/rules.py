"""规则层：词典粗筛、回复质检、离线兜底。

存在的意义有两个：
1. 给模型提供线索（进程1 的 precheck），也给质检提供确定性判据（进程2 的 quality_check）；
2. 模型挂了 / 服务挂了的时候，链路还能给出「不惊艳但正确」的结果（后端的 degraded 分支）。
"""

from __future__ import annotations

import re
from typing import Any

from .protocol import Label, ReplyResult, SentimentResult

POS_WORDS = (
    "开心 高兴 快乐 激动 期待 太好了 谢谢 感谢 顺利 通过 录取 升职 加薪 拿到 自豪 满意 轻松 舒服 "
    "喜欢 幸运 惊喜 棒 赞 完美 成功 进步 治愈 幸福 值得 放松 好起来 有希望 给力 美好 热爱 开挂"
).split()

NEG_WORDS = (
    "难过 伤心 焦虑 压力 烦 累 崩溃 委屈 生气 愤怒 孤独 寂寞 害怕 恐惧 失眠 想哭 哭了 失业 分手 "
    "失败 内疚 自责 后悔 绝望 无助 讨厌 恶心 麻木 摆烂 心累 内耗 加班 熬夜 吵架 被骂 拖延 "
    "来不及 搞砸 完蛋 撑不住 好难 不想动 没意思 疲惫 压抑 烦躁 郁闷"
).split()

CRISIS_WORDS = (
    "自杀 自残 不想活 活着没意思 轻生 结束生命 跳楼 割腕 死了算了 消失算了 一了百了 没有活下去"
).split()

# 关键词匹配不到「活着没什么意思」这类插入语，所以危机判断再叠一层正则
CRISIS_PATTERNS = [
    re.compile(p)
    for p in [
        r"不想活",
        r"活着.{0,8}(没|没有|毫无)\S{0,4}(意思|意义)",
        r"(人生|生活).{0,4}(没|没有|毫无)\S{0,4}(意思|意义)",
        r"活不下去",
        r"自(杀|残)",
        r"轻生",
        r"结束(自己的)?生命",
        r"跳楼|割腕|上吊",
        r"死了?算了",
        r"消失算了",
        r"一了百了",
        r"没有?活下去的(理由|必要)",
    ]
]

# 说教 / 有毒的正向 / 越界诊断——命中任何一条，回复直接判不合格
BANNED_PATTERNS = [
    "你应该", "你不该", "你必须", "你不能", "想开点", "想开一点", "别想太多",
    "没什么大不了", "这算什么", "别人也一样", "比你惨", "至少你还有",
    "开心点", "笑一笑就好了", "振作起来", "加油就好了", "不要难过",
    "你得了", "你有抑郁症", "你这是心理病", "包治", "保证好",
]

_VAGUE_PATTERNS = ["一切都会好的", "时间会治愈", "都会过去的", "明天会更好"]

_CJK = re.compile(r"[\u4e00-\u9fa5]")


def _hits(text: str, words: list[str]) -> list[str]:
    return [w for w in words if w in text]


def is_crisis(text: str) -> bool:
    """危机表达只做「命中即提醒」，不做概率判断——宁可多提醒一次。"""
    if _hits(text, CRISIS_WORDS):
        return True
    return any(p.search(text) for p in CRISIS_PATTERNS)


def lexicon_hint(text: str) -> dict[str, object]:
    pos, neg = _hits(text, POS_WORDS), _hits(text, NEG_WORDS)
    return {"pos": pos, "neg": neg, "crisis": is_crisis(text)}


def rule_sentiment(text: str) -> SentimentResult:
    """词典兜底：区分不了反讽，但足够让链路在离线时仍然可用。"""
    pos, neg = _hits(text, POS_WORDS), _hits(text, NEG_WORDS)
    crisis = is_crisis(text)
    if crisis:
        label: Label = "negative"
        emotion, intensity = "绝望", 0.95
    elif len(pos) > len(neg):
        label, emotion, intensity = "positive", "积极", min(0.9, 0.45 + 0.15 * len(pos))
    elif len(neg) > len(pos):
        label, emotion, intensity = "negative", "低落", min(0.9, 0.45 + 0.15 * len(neg))
    else:
        label, emotion, intensity = "neutral", "平静", 0.4
    return SentimentResult(
        label=label,  # type: ignore[arg-type]
        emotion=emotion,
        confidence=0.35 if (pos and neg) else 0.5,
        intensity=intensity,
        reason=f"词典命中：正向{len(pos)}个、负向{len(neg)}个" + ("、含危机词" if crisis else ""),
        keywords=(pos + neg)[:3],
        source="rule",
        notes=["degraded: 未使用大模型"],
    )


def post_verify(result: SentimentResult, hint: dict[str, Any]) -> tuple[SentimentResult, list[str]]:
    """模型给出结果之后的确定性压制（两个版本都走这一步）。

    - 命中危机词但模型判成非负向：强制改成 negative，强度抬高；
    - 模型判正向、词典却是负向词更多，且它自己也没把握：把置信度压下去，触发复核。
    """
    notes: list[str] = []
    if hint.get("crisis") and result.label != "negative":
        notes.append("命中危机词，标签强制改为 negative")
        result.label = "negative"
        result.intensity = max(result.intensity, 0.9)
        result.emotion = result.emotion if result.emotion not in ("", "平静") else "绝望"
    if (
        result.label == "positive"
        and len(hint.get("neg") or []) > len(hint.get("pos") or [])
        and result.confidence < 0.7
    ):
        result.confidence = min(result.confidence, 0.5)
        notes.append("与词典线索冲突，置信度下调")
    return result, notes


def pick_strategy(label: Label, text: str) -> str:
    """标签 -> 策略。危机优先，其次是情绪方向。"""
    if is_crisis(text):
        return "crisis"
    return {"positive": "encourage", "negative": "soothe", "neutral": "listen"}[label]


_CANNED = {
    "encourage": "听你这么说我都跟着高兴起来了——{kw}这件事你确实花了不少心思，开心是应该的。这份劲头你打算怎么接着用？",
    "soothe": "能感觉到你现在被「{kw}」这件事压得有点沉，先不用急着振作，难受一会儿也没关系。要不要先给自己倒杯水，慢慢跟我说说最卡的是哪一步？",
    "listen": "嗯，「{kw}」这事我听着呢，感觉你是在很平静地讲一件已经消化过的事。是哪一点让你想起来的？",
    "crisis": "你愿意说出来，说明你还在努力。此刻请先联系一个你信任的人，让他待在你身边；也建议拨打全国 24 小时心理援助热线 400-161-9995，或者去最近的医院急诊。你的安全比什么都重要。",
}

_CANNED_TIPS = {
    "encourage": ["把今天让自己开心的一件小事记下来", "找个机会把这份好消息分享给一个人"],
    "soothe": ["做 4-7-8 呼吸三轮", "把此刻最烦的一件事写成一句话"],
    "listen": [],
    "crisis": ["现在就给可信任的人打电话", "移除身边的危险物品，去有人的地方"],
}


def rule_reply(label: Label, text: str, strategy: str | None = None) -> ReplyResult:
    strategy = strategy or pick_strategy(label, text)
    kw = (_hits(text, POS_WORDS) + _hits(text, NEG_WORDS) or [text[:8]])[0]
    return ReplyResult(
        strategy=strategy,  # type: ignore[arg-type]
        reply=_CANNED[strategy].format(kw=kw),
        tips=_CANNED_TIPS[strategy],
        follow_up="",
        source="rule",
        notes=["degraded: 未使用大模型"],
    )


def check_reply_rules(text: str, label: Label, reply: str) -> str | None:
    """确定性质检。返回不合格原因，合格返回 None。

    这些判据不依赖模型，所以「模型自己写、模型自己判」的循环不会无限放水。
    """
    body = (reply or "").strip()
    if len(body) < 20:
        return "回复过短，没有接住具体内容"
    for bad in BANNED_PATTERNS:
        if bad in body:
            return f"出现说教/越界表达「{bad}」"
    vague = [v for v in _VAGUE_PATTERNS if v in body]
    if vague and len(body) < 60:
        return f"只有套话（{vague[0]}），缺少具体回应"
    if label == "negative" and not is_crisis(text) and not _CJK.search(body):
        return "负向情绪却给了不含中文的回复"
    if label == "positive" and any(w in body for w in ("可惜", "但是你别", "不过也别太")):
        return "正向情绪却泼了冷水"
    return None
