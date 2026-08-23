from sentence_transformers import SentenceTransformer
import numpy as np

# 1. 加载本地 BGE 模型（BERT 架构，中文语义向量）
model = SentenceTransformer("BAAI/bge-small-zh-v1.5")

# 2. 待检索文本与数据库文本
query = "我今天很开心"
documents = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错",
]

# 3. 编码为向量（normalize 后可直接做内积近似余弦相似度）
query_vec = model.encode([query], normalize_embeddings=True)[0]
doc_vecs = model.encode(documents, normalize_embeddings=True)

# 4. 计算相似度并排序
scores = doc_vecs @ query_vec  # 归一化向量的内积 = 余弦相似度
order = np.argsort(scores)[::-1]

print(f"查询文本：{query}\n")
for i in order:
    print(f"[{scores[i]:.4f}] {documents[i]}")
