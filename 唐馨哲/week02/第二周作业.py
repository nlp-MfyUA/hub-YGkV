import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-mouweajeocchkgiuqicvfgxalxabdarusgpqkpcbhciqygjs",
    base_url="https://api.siliconflow.cn/v1"
)

def extract_relationship(text: str):
    system_prompt = """
你是人物情感关系抽取专家。
严格遵守规则：
1. 输出顶层为JSON对象，对象包含唯一key: `relations`，值为关系数组；
2. 数组每一条固定字段 source, relation, target；
3. **把文本里所有明确存在的关系全部抽取，一条都不能遗漏！**
4. 禁止增加多余说明、markdown、```；输出内容直接可被json.loads解析。

输入示例：小明喜欢小姚，但是小姚喜欢小王。
标准输出模板：
{
    "relations": [
        {"source": "小明", "relation": "爱慕", "target": "小姚"},
        {"source": "小姚", "relation": "爱慕", "target": "小王"}
    ]
}
"""

    response = client.chat.completions.create(
        model="MiniMaxAI/MiniMax-M2.5",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        stream=False,
        response_format={"type": "json_object"}
    )
    json_str = response.choices[0].message.content
    data = json.loads(json_str)
    return data["relations"]


if __name__ == "__main__":
    input_sentence = "小李觉得小赵很可恶，但是小白觉得小赵是个好人，小李觉得小白不好亲近。"
    relations = extract_relationship(input_sentence)
    print(json.dumps(relations, ensure_ascii=False, indent=4))
