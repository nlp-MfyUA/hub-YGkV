from agents import Agent

import agent_config

PROMPT = (
    "你是一个强大的翻译助手，需要将用户的输入翻译成英文。"
    "并把译文填入 result 字段；query_input 原样保留用户输入。\n"
    "示例：输入'我喜欢机器学习' → query_input='我喜欢机器学习', result='I like machine learning'"
)

english = Agent(
    name="english",
    instructions=PROMPT,
    model=agent_config.model,
    output_type=agent_config.Output
)


if __name__ == "__main__":
    from agents import Runner
    result = Runner.run_sync(english, "我爱深度学习")
    print(result.final_output_as(agent_config.Output, raise_if_incorrect_type=True))