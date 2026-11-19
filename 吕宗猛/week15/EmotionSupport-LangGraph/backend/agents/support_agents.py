"""三个回应 Agent：正向鼓励、负面排解、中性陪伴。"""

from __future__ import annotations

import config
from agents.base import build_model, mock_reply
from schemas import AGENT_NAMES, EmotionResult

ENCOURAGE_PROMPT = """你是「正向鼓励 Agent」，擅长把用户此刻的好情绪接住并延长。

工作原则：
1. 先具体回应他分享的事情，指出其中值得肯定的努力、选择或品质，不要空泛地说“你真棒”。
2. 帮他把这份感受和具体的价值联系起来，让他知道为什么值得记住。
3. 最后给一个温和、可选的延伸建议（例如记录、分享、庆祝），不要说教。
4. 用中文，2-4 个短段落，每段 1-3 句；语气温暖、真诚、有分寸。
5. 不要否定或泼冷水，不要用“但是”转折。"""

COMFORT_PROMPT = """你是「负面排解 Agent」，擅长先接住情绪，再帮用户把压力变小。

工作原则：
1. 先用一句话准确命名你听到的情绪（焦虑、委屈、愤怒、疲惫、自责等），让用户感到被理解。
2. 不急着讲道理，不比较，不说“别想太多”“至少你还有……”。
3. 帮用户把问题拆成一个最小的可控动作，或给一个 1-3 分钟能完成的调节练习。
4. 最后传递稳定的支持，让用户知道不需要一个人扛。
5. 用中文，2-4 个短段落，每段 1-3 句；语气平稳、克制、有力量。"""

class BaseSupportAgent:
    """回应 Agent 的公共基类。"""

    key: str = "neutral"
    name: str = ""
    system_prompt: str = ""

    def __init__(self) -> None:
        self._model = build_model(config.REPLY_MODEL, temperature=config.LLM_TEMPERATURE)

    async def respond(self, user_input: str, emotion: EmotionResult, history_text: str = "") -> str:
        if config.MOCK_MODE:
            return mock_reply(self.key, user_input, emotion)

        history_block = (history_text + "\n\n") if history_text else ""
        human = (
            history_block
            + "用户原话：\n" + user_input + "\n\n"
            "情感识别结果：\n"
            f"- 标签：{emotion.label_zh}\n"
            f"- 置信度：{emotion.confidence:.0%}\n"
            f"- 强度：{emotion.intensity}/5\n"
            f"- 依据：{emotion.reason or '无'}\n\n"
            "请依据以上信息，直接给用户一段回应。"
        )
        try:
            response = await self._model.ainvoke(
                [("system", self.system_prompt), ("human", human)]
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{self.name} 调用失败：{type(exc).__name__}: {exc}") from exc

        content = response.content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            content = "".join(parts)
        return str(content).strip()


class EncourageAgent(BaseSupportAgent):
    key = "encourage"
    name = AGENT_NAMES["encourage"]
    system_prompt = ENCOURAGE_PROMPT


class ComfortAgent(BaseSupportAgent):
    key = "comfort"
    name = AGENT_NAMES["comfort"]
    system_prompt = COMFORT_PROMPT


SUPPORT_AGENTS: dict[str, BaseSupportAgent] = {
    "encourage": EncourageAgent(),
    "comfort": ComfortAgent(),
}


def get_support_agent(route: str) -> BaseSupportAgent:
    return SUPPORT_AGENTS.get(route, SUPPORT_AGENTS["comfort"])
