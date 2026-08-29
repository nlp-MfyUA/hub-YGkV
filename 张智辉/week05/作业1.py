"""
使用 sentence-transformers 和 BGE 模型进行文本检索
"""

from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("../BAAI/bge-small-zh-v1.5/")  # sentence-bert 微调之后的

# 2. 待检索的文本（query）
query = "我今天很开心"

# 3. 数据库文本（候选集）
corpus = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错",
]

# 4. 对所有文本进行编码（生成向量）
query_embedding = model.encode(query, normalize_embeddings=True)
corpus_embeddings = model.encode(corpus, normalize_embeddings=True)

# 5. 计算余弦相似度并排序
scores = np.dot(corpus_embeddings, query_embedding)  # 已归一化，点积 = 余弦相似度

# 获取按相似度降序排列的索引
ranked_indices = np.argsort(scores)[::-1]

# 6. 输出结果
print("=" * 50)
print(f"检索文本: {query}")
print("=" * 50)
print("检索结果（按相似度排序）: ")
print("-" * 50)
for rank, idx in enumerate(ranked_indices, 1):
    print(f"第 {rank} 名: {corpus[idx]}  (相似度: {scores[idx]:.4f})")
print("=" * 50)
