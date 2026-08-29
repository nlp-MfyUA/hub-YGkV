from openai import OpenAI

# 初始化客户端，指向 Ollama 的本地服务
client = OpenAI(
    base_url="http://localhost:11434/v1",  # Ollama API 地址
    api_key="1111"  # Ollama 默认无需真实 API Key，填任意值即可
)

while True:
    message = input("请输入消息（输入 'exit' 退出）：")
    if message == "exit":
        break
    
    # 发送请求
    response = client.chat.completions.create(
        model="qwen3-0.6b",
        messages=[
            {"role": "system", "content": "你是一个有帮助的助手。"},
            {"role": "user", "content": message}
        ],
        temperature=0.7,
        max_tokens=512
    )
    
    # 打印结果
    print(response.choices[0].message.content)