from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from openai import OpenAI
from agents import Agent, Runner, function_tool
import os

app = FastAPI(title="OpenAI Agents 情感Agent")
client = OpenAI(
    api_key=os.getenv("LLM_API_KEY", "sk-2748ea51bf574999aeadd7a81130beeb"),
    base_url=os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
)

# 子Agent1：情感识别Agent
emotion_agent = Agent(
    name="情感识别Agent",
    instructions="你只输出一个单词：positive / negative / neutral，严格遵守，不要别的内容",
    model="qwen-turbo"
)

# 子Agent2：情绪安抚/鼓励Agent
reply_agent = Agent(
    name="情绪应答Agent",
    instructions="""
收到情绪标签和用户原话：
如果是positive：温暖鼓励用户
如果是negative：温柔排解、安抚情绪
如果是neutral：友好自然对话
输出自然中文，不要markdown
""",
    model="qwen-turbo"
)

# 主Agent串联流程
main_agent = Agent(
    name="主调度Agent",
    instructions="先调用情感识别Agent拿到情绪，再把【用户输入+情绪】交给应答Agent生成回复，最后返回情绪和回答",
    handoffs=[emotion_agent, reply_agent]
)

@app.get("/", response_class=HTMLResponse)
async def index():
    html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>OpenAI-Agents 情感识别Agent</title>
<style>
.box{max-width:700px;margin:30px auto;padding:20px;}
textarea{width:100%;height:100px;padding:8px;box-sizing:border-box}
button{margin-top:10px;padding:8px 16px;cursor:pointer}
#result{margin-top:16px;padding:12px;background:#f5f5f5;border-radius:6px}
</style>
</head>
<body>
<div class="box">
<h3>情感倾诉小助手（OpenAI Agents SDK版）</h3>
<textarea id="userText" placeholder="在这里输入你的心情..."></textarea>
<br>
<button onclick="send()">提交</button>
<div id="result"></div>
</div>
<script>
async function send(){
    const text = document.getElementById("userText").value;
    const fd = new FormData();
    fd.append("user_input", text);
    const ret = await fetch("/chat",{method:"POST",body:fd});
    const data = await ret.json();
    document.getElementById("result").innerHTML =
        `<div>识别情绪：<b>${data.emotion}</b></div><div>回复：${data.reply}</div>`
}
</script>
</body>
</html>
"""
    return html

@app.post("/chat")
async def chat(user_input: str = Form(...)):
    # 第一步：调用情感识别Agent
    emo_result = await Runner.run(emotion_agent, user_input)
    emo = emo_result.final_output.strip()
    # 第二步：交给应答Agent
    prompt = f"用户输入：{user_input}，识别情绪：{emo}"
    reply_result = await Runner.run(reply_agent, prompt)
    return {
        "user_input": user_input,
        "emotion": emo,
        "reply": reply_result.final_output
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("openai_agents_emotion:app", host="0.0.0.0", port=8002)
