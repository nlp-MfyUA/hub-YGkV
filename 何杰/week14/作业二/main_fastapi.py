# main_fastapi.py
import uuid
import json
import os
import requests
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from kafka import KafkaProducer
import redis
import chromadb
from sentence_transformers import SentenceTransformer
from config import *

app = FastAPI(title="Kafka-MinerU多模态RAG")
app.mount("/static", StaticFiles(directory="static"), name="static")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
producer = KafkaProducer(
    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

# 向量库
chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
collection = chroma_client.get_or_create_collection(name="mm_rag_pdf")
emb_model = SentenceTransformer("all-MiniLM-L6-v2")

# 首页
@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

# 上传PDF接口，推送到Kafka
@app.post("/upload_pdf")
async def upload_pdf(file: UploadFile = File(...)):
    task_id = str(uuid.uuid4())
    save_path = os.path.join(UPLOAD_DIR, f"{task_id}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(await file.read())
    task_info = {
        "task_id": task_id,
        "pdf_path": save_path,
        "file_name": file.filename
    }
    redis_client.set(f"task:{task_id}", "pending")
    producer.send(KAFKA_TOPIC_PDF, value=task_info)
    producer.flush()
    return JSONResponse({"task_id": task_id, "filename": file.filename, "status": "pending"})

# 查询任务状态
@app.get("/task_status/{task_id}")
async def get_task_status(task_id: str):
    status = redis_client.get(f"task:{task_id}")
    if not status:
        return JSONResponse({"task_id": task_id, "status": "not_found"})
    return JSONResponse({"task_id": task_id, "status": status})

# 多模态问答接口：question文本 + 可选image图片
@app.post("/mm_chat")
async def mm_chat(question: str = Form(...), image: UploadFile | None = File(None)):
    # 1. 检索知识库
    q_emb = emb_model.encode(question).tolist()
    res = collection.query(query_embeddings=[q_emb], n_results=3)
    ref_docs = res["documents"][0]
    ref_metas = res["metadatas"][0]
    context = "\n".join(ref_docs)

    # 2. 构造Qwen-VL多模态消息
    messages = [
        {
            "role": "system",
            "content": "你是多模态文档问答助手，基于参考文档回答，支持图文混排输出，图片使用markdown格式展示。"
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"参考文档：{context}\n用户问题：{question}"}
            ]
        }
    ]
    # 如果上传了图片，追加图片
    if image is not None:
        img_name = f"{uuid.uuid4()}_{image.filename}"
        img_path = os.path.join(IMAGE_CACHE_DIR, img_name)
        with open(img_path, "wb") as f:
            f.write(await image.read())
        img_url = f"/static/images/{img_name}"
        messages[1]["content"].append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })

    # 调用VL模型
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    payload = {
        "model": LLM_MODEL,
        "messages": messages
    }
    resp = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload)
    llm_result = resp.json()
    answer = llm_result["choices"][0]["message"]["content"]
    return JSONResponse({"answer": answer, "reference": ref_docs})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_fastapi:app", host="0.0.0.0", port=8000)
