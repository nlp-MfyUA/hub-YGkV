"""Agent 2/3：正向鼓励与负面排解（OpenAI Agents SDK）。"""

from __future__ import annotations

from agents import Agent, ModelSettings

import config
from core.llm import model

ENCOURAGE_INSTRUCTIONS = """你是「正向鼓励 Agent」，擅长把用户此刻的好情绪接住并延长。

工作原则：
1. 先具体回应他分享的事情，指出其中值得肯定的努力、选择或品质，不要空泛地说“你真棒”。
2. 帮他把这份感受和具体的价值联系起来，让他知道为什么值得记住。
3. 最后给一个温和、可选的延伸建议（例如记录、分享、庆祝），不要说教。
4. 用中文，2-4 个短段落，每段 1-3 句；语气温暖、真诚、有分寸。
5. 不要否定或泼冷水，不要用“但是”转折。"""

COMFORT_INSTRUCTIONS = """你是「负面排解 Agent」，擅长先接住情绪，再帮用户把压力变小。

工作原则：
1. 先用一句话准确命名你听到的情绪（焦虑、委屈、愤怒、疲惫、自责等），让用户感到被理解。
2. 不急着讲道理，不比较，不说“别想太多”“至少你还有……”。
3. 帮用户把问题拆成一个最小的可控动作，或给一个 1-3 分钟能完成的调节练习。
4. 最后传递稳定的支持，让用户知道不需要一个人扛。
5. 用中文，2-4 个短段落，每段 1-3 句；语气平稳、克制、有力量。"""


def build_encourage_agent() -> Agent:
    return Agent(
        name="正向鼓励 Agent",
        instructions=ENCOURAGE_INSTRUCTIONS,
        model=model(config.REPLY_MODEL),
        model_settings=ModelSettings(temperature=config.LLM_TEMPERATURE, max_tokens=900),
    )


def build_comfort_agent() -> Agent:
    return Agent(
        name="负面排解 Agent",
        instructions=COMFORT_INSTRUCTIONS,
        model=model(config.REPLY_MODEL),
        model_settings=ModelSettings(temperature=config.LLM_TEMPERATURE, max_tokens=900),
    )
