# consumer.py
import json
import os
import redis
from kafka import KafkaConsumer
from mineru import MinerU
import chromadb
from sentence_transformers import SentenceTransformer
from config import *

os.makedirs(MINERU_OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
consumer = KafkaConsumer(
    KAFKA_TOPIC_PDF,
    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
    value_deserializer=lambda x: json.loads(x.decode("utf-8")),
    auto_offset_reset="earliest",
    group_id="pdf-mineru-consumer-group"
)

# 初始化向量库 & 嵌入模型
client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
collection = client.get_or_create_collection(name="mm_rag_pdf")
emb_model = SentenceTransformer("all-MiniLM-L6-v2")

mineru = MinerU()

def process_pdf_task(task: dict):
    task_id = task["task_id"]
    pdf_path = task["pdf_path"]
    file_name = task["file_name"]
    redis_client.set(f"task:{task_id}", "running")
    try:
        # MinerU解析PDF，输出markdown+图片
        result = mineru(
            pdf_path,
            output_dir=os.path.join(MINERU_OUTPUT_DIR, task_id)
        )
        md_content = result["markdown"]
        image_list = result.get("images", [])

        # 分片，存入向量库，metadata带上图片路径
        chunks = []
        metas = []
        ids = []
        chunk_size = 800
        for i in range(0, len(md_content), chunk_size):
            chunk = md_content[i:i+chunk_size]
            chunks.append(chunk)
            metas.append({
                "task_id": task_id,
                "file_name": file_name,
                "images": json.dumps(image_list)
            })
            ids.append(f"{task_id}-{i}")

        if chunks:
            embeddings = emb_model.encode(chunks).tolist()
            collection.add(
                documents=chunks,
                embeddings=embeddings,
                metadatas=metas,
                ids=ids
            )
        redis_client.set(f"task:{task_id}", "success")
        print(f"✅ task {task_id} 解析完成")
    except Exception as e:
        redis_client.set(f"task:{task_id}", "failed")
        print(f"❌ task {task_id} 失败：{e}")

if __name__ == "__main__":
    print("Kafka MinerU消费进程启动，等待PDF任务...")
    for msg in consumer:
        task_data = msg.value
        process_pdf_task(task_data)
