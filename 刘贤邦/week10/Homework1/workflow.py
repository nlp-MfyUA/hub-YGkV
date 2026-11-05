# 用户输入文本，判断下文本的语种（是什么语言的）。如果是非中文的，则翻译为中文；如果是中文，则翻译为英文
# 拆分为2种Agent：
# 1.判断语种
# 2.翻译
# 串联Agent

from agents import Runner

from agent_config import Output
from agent.judge_agent import judge, IsChinese
from agent.chinese_agent import chinese
from agent.english_agent import english

class Workflow:
    def __init__(self, judge_agent, chinese_agent, english_agent):
        self.judge_agent = judge_agent
        self.chinese_agent = chinese_agent
        self.english_agent = english_agent

    def translate(self, text: str) -> Output:

        # 1. 先判断输入语种
        judge_result = Runner.run_sync(self.judge_agent, text)
        is_chinese = judge_result.final_output_as(IsChinese, raise_if_incorrect_type=True)

        # 2. 进行翻译
        if is_chinese.is_chinese:
            translation = Runner.run_sync(self.english_agent, text).final_output_as(Output, raise_if_incorrect_type=True)
        else:
            translation = Runner.run_sync(self.chinese_agent, text).final_output_as(Output, raise_if_incorrect_type=True)

        # 3.返回翻译结果
        return translation

if __name__ == "__main__":
    workflow = Workflow(judge, chinese, english)

    print(workflow.translate("我喜欢深度学习"))
    print(workflow.translate("I love deep learning"))
