from openai import OpenAI
client = OpenAI(
    base_url = "http://localhost:11434/v1",
    api_key = "111"
)

response = client.chat.completions.create(
    model = "qwen3:0.6b",
    messages = [
        {"role" : "system", "content" : "你是一个有帮助的助手。"},
        {"role" : "user", "content" : "你好"}
    ],
    temperature=0.7,
    max_tokens=512
)

print(response.choices[0].message.content)

