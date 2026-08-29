from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import os, json

# ========== 1. 模型路径（指向包含 config.json 的那一层）==========
MODEL_PATH = r"E:\modelscope_cache\models\BAAI--bge-small-zh-v1.5\snapshots\master"

# 路径自检：自动往子目录找 config.json
if not os.path.isfile(os.path.join(MODEL_PATH, "config.json")):
    for entry in os.listdir(MODEL_PATH):
        sub = os.path.join(MODEL_PATH, entry)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "config.json")):
            MODEL_PATH = sub
            break

# ========== 2. 加载模型 ==========
model = SentenceTransformer(MODEL_PATH)
print("✅ 模型加载完成")

# ========== 3. 构建语料库 ==========
corpus = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]

corpus_embeddings = model.encode(corpus, normalize_embeddings=True)

# ========== 4. 只返回最相似的一条 ==========
def search(query: str):
    instruction = "为这个句子生成表示以用于检索相关文章："
    q_emb = model.encode(instruction + query, normalize_embeddings=True)

    scores = cosine_similarity([q_emb], corpus_embeddings)[0]

    # 取相似度最高的那一条
    best_idx = scores.argmax()
    return corpus[best_idx], float(scores[best_idx])

# ========== 5. 测试 ==========
if __name__ == "__main__":
    test_queries = [
        "我今天很开心"
    ]

    for q in test_queries:
        text, score = search(q)
        print(f"🔍 查询: 「{q}」")
        print(f"   🎯 最相似: {text}  | 相似度: {score:.4f}\n")