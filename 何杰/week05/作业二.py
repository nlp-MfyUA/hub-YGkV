from openai import OpenAI

# 初始化客户端，指向 Ollama 的本地服务
client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="1111"
)

# 发送请求
response = client.chat.completions.create(
    model="qwen3:0.6b",
    messages=[
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么我可以帮你的吗？"},
        {"role": "user", "content": "你能帮我做什么？"}
    ],
    temperature=0.7,
    max_tokens=512
)

# 打印结果
print(response.choices[0].message.content)
