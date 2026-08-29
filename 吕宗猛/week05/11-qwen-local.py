import time

from openai import OpenAI, OpenAIError

model = OpenAI(
    base_url="http://127.0.0.1:11434/v1",
    api_key="123456",
    timeout=15
)
start_time = time.perf_counter()
try:
    response = model.chat.completions.create(
        # 消息列表
        messages=[
            {"role": "system", "content": "你是一个有帮助的助手"},
            {"role": "user", "content": "你好"}],
        model="qwen3-cpu"
    )
    end_time = time.perf_counter()
    print(f'耗时:\n  {(end_time - start_time):.3f}秒')
    if response:
        print(f'模型回复:\n  {response.choices[0].message.content}')
    else:
        print(f'模型调用失败,请重新核实!')
except OpenAIError as oae:
    print(f'模型调用异常:\n{oae}')
