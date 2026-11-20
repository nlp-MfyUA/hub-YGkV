from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
import os

app = FastAPI(title="LangGraph 情感Agent")

# 大模型配置
llm = ChatOpenAI(
    api_key=os.getenv("LLM_API_KEY", "your-key"),
    base_url=os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    model="qwen-turbo"
)

# 定义状态
class AgentState(BaseModel):
    user_input: str
    emotion: str = ""
    reply: str = ""

# 节点1：情感识别
def emotion_recognize(state: AgentState):
    prompt = f"""
你是情感识别器，只输出一个单词：positive / negative / neutral
用户输入：{state.user_input}
规则：
positive：开心、兴奋、喜悦、满意
negative：难过、委屈、焦虑、生气、低落
neutral：平淡陈述，无明显情绪
只返回单词，不要多余文字
"""
    resp = llm.invoke(prompt)
    return {"emotion": resp.content.strip()}

# 节点2：情绪应答
def emotion_reply(state: AgentState):
    emo = state.emotion
    user_text = state.user_input
    if emo == "positive":
        prompt = f"用户现在情绪很好，用户原话：{user_text}，写一段温暖鼓励的话，简短自然"
    elif emo == "negative":
        prompt = f"用户现在情绪低落，用户原话：{user_text}，温柔安抚、排解情绪，不要说教"
    else:
        prompt = f"用户平淡陈述：{user_text}，友好自然回应"
    resp = llm.invoke(prompt)
    return {"reply": resp.content.strip()}

# 构建图
builder = StateGraph(AgentState)
builder.add_node("recognize", emotion_recognize)
builder.add_node("reply_node", emotion_reply)
builder.add_edge(START, "recognize")
builder.add_edge("recognize", "reply_node")
builder.add_edge("reply_node", END)
graph = builder.compile()

# 前端页面
@app.get("/", response_class=HTMLResponse)
async def index():
    html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>LangGraph情感识别Agent</title>
<style>
.box{max-width:700px;margin:30px auto;padding:20px;}
textarea{width:100%;height:100px;padding:8px;box-sizing:border-box}
button{margin-top:10px;padding:8px 16px;cursor:pointer}
#result{margin-top:16px;padding:12px;background:#f5f5f5;border-radius:6px}
</style>
</head>
<body>
<div class="box">
<h3>情感倾诉小助手（LangGraph版）</h3>
<textarea id="userText" placeholder="在这里输入你的心情..."></textarea>
<br>
<button onclick="send()">提交</button>
<div id="result"></div>
</div>
<script>
async function send(){
    const text = document.getElementById("userText").value;
    const res = await fetch("/chat",{
        method:"POST",
        body:new FormData(document.createElement("form"))
    });
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
    res = graph.invoke({"user_input": user_input})
    return {
        "user_input": user_input,
        "emotion": res["emotion"],
        "reply": res["reply"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("langgraph_emotion_agent:app", host="0.0.0.0", port=8001)
