"""多 Agent 实现：情感识别 + 三个回应 Agent。"""

from agents.emotion_agent import EmotionAgent
from agents.support_agents import ComfortAgent, EncourageAgent

__all__ = ["EmotionAgent", "EncourageAgent", "ComfortAgent"]
