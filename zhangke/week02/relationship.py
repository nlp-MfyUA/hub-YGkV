from openai import OpenAI

client = OpenAI(
    api_key = "MY_API_KEY",
    base_url = "https://api.deepseek.com"
)

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages= [
        {"role": "system", "content": "根据示例格式，得到两个人之间的关系。"},
        {"role": "user", "content":"""
        示例1：A喜欢B，但B喜欢C ->得到任务关系图谱的JSON输出示例：
        "relations":
        [
            {
                "source: "A",
                "relation: "爱慕",
                "target": "B"
            },
            {
                "source: "B",
                "relation: "爱慕",
                "target": "C"
            }
            
        ]
        示例2：D不喜欢E，D喜欢F ->得到人物关系图谱的JSON输出示例：
        "relations":
        [
            {
                "source: "D",
                "relation: "讨厌",
                "target": "E"
            },
            {
                "source: "D",
                "relation: "爱慕",
                "target": "F"
            }
        ]
        需要分析“小明喜欢小姚，但是小姚喜欢小王”的任务图谱关系
        """},
    ],
    stream=False,
    response_format={"type": "json_object"},
)

print(f"输出：{response.choices[0].message.content}\n")

