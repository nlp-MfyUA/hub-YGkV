from sentence_transformers import SentenceTransformer

# 1. 加载本地 BGE 模型
model = SentenceTransformer("./models/BAAI/bge-small-zh-v1.5")

# 2. 查询文本
query = "我今天很开心"

# 3. 待检索文本
documents = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]

# 4. 转成 embedding
query_embedding = model.encode(
    query,
    normalize_embeddings=True
)

document_embeddings = model.encode(
    documents,
    normalize_embeddings=True
)

# 5. 计算相似度
scores = document_embeddings @ query_embedding

# 6. 查看每条文本的分数
for document, score in zip(documents, scores):
    print(f"{document}: {score:.4f}")

# 7. 找最相似文本
best_index = scores.argmax()

print("\n检索结果：")
print(documents[best_index])