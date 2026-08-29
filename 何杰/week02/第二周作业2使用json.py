from openai import OpenAI
import json

class RelationAgent:
    def __init__(self, api_key: str, base_url: str = None, model: str = "Qwen/Qwen3.5-9B"):
        """
        情感人物关系抽取智能体，依赖LLM JSON Mode能力
        :param api_key: LLM接口密钥
        :param base_url: 兼容OpenAI接口的代理/国内大模型地址
        :param model: 支持json_mode的模型
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        # 系统Prompt：限定输出格式、抽取规则
        '''
        这里定义输出的时候，原本的作业格式是[{"source": "小明", "relation": "爱慕", "target": "小姚"}],
        但是因为强制使用了json_object，输出的时候只会是{}，因此导致了我最终输出的结果一直是错误的一直会丢数据，我预期有多条结果的时候
        大部分的结果都是只有一组数据，偶尔会出现多条的输出数据，因此在定义的时候做了修改，把整个关系塞到一个新的字典中去
        或者把作业的数组[]去掉，直接就是使用字典{}的格式输出，那么原来的定义就是可以正常使用的。
        '''    

        self.system_prompt = """
        你是人物情感关系抽取智能体，严格遵循规则：
        1. 只提取人与人之间爱慕、喜欢、暗恋这类情感关系；
        2. 最终输出顶层必须是JSON数组 []，绝对不能是{}对象！！禁止任何解释、多余文字、markdown注释；
        3. 数组内每个对象固定三字段：
        - source: 发起情感的人物（字符串）
        - relation: 关系词，喜欢/爱慕统一填"爱慕"
        - target: 被爱慕的人物（字符串）
        4. 一句文本有多组关系则输出多条对象；
        5. 无情感关系输出空数组 []。
        示例输入：小明喜欢小姚
        示例输出：
        {
            "relation_list": [
                {"source": "小明", "relation": "爱慕", "target": "小姚"}
            ]
        }
        错误禁止：直接返回{"source":"xx"}这种单层大括号，绝对不允许。
        """

    def extract_relation(self, text: str) -> list:
        """输入文本，返回结构化人物关系列表"""
        resp = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},  # 开启JSON Mode强制输出JSON
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text}
            ],
            max_tokens=200,  # 最大输出200字
            temperature=0.0  # 温度置0保证输出稳定一致
        )
        json_str = resp.choices[0].message.content 
        relation_list = json.loads(json_str)
        return relation_list



if __name__ == "__main__":
    # 1. 初始化智能体，替换为自己的key与接口地址
    AGENT = RelationAgent(
        api_key="sk-halxmsnmydbzgughfdiqypyzjjcedjjbsyuubmqatarghooc",
         base_url="https://api.siliconflow.cn",  # 硅基流动
         model="Pro/MiniMaxAI/MiniMax-M2.5"
    )

    
    input_text = "小明喜欢小姚，但是小姚喜欢小王，小王喜欢小张。"
    result = AGENT.extract_relation(input_text)

    # 格式化打印人物关系图谱
    print("人物关系图谱")
    print(json.dumps(result, ensure_ascii=False, indent=2)) 
