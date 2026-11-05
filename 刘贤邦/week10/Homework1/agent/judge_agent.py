from agents import Agent
from pydantic import BaseModel, Field

import agent_config


PROMPT = (
    "判断用户输入是否为中文，是则 is_chinese 为True，否则为False"
)

class IsChinese(BaseModel):
    """用于判断语种"""
    is_chinese: bool = Field(description="是否是中文，如果用户输入为中文，则返回True，如果不是中文，则返回False")

# 创建Agent
judge = Agent(
    name = "judge",
    instructions = PROMPT,
    model = agent_config.model,
    output_type=IsChinese
)

if __name__ == "__main__":
    from agents import Runner

    result = Runner.run_sync(judge, "This is a word")
    print(result.final_output_as(IsChinese, raise_if_incorrect_type=True))
