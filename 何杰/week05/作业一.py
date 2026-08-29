from sentence_transformers import SentenceTransformer
import numpy as np

# 1.加载本地bge模型
model = SentenceTransformer("./BAAI/bge-small-zh-v1.5")

# 2.待检索query、知识库文本
query = "我今天很开心"
docs = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]

# 3.BGE官方要求：检索query前面加固定前缀，文档不用
query_emb = model.encode("为这个句子生成表示以用于检索查询：" + query, normalize_embeddings=True)
doc_embs = model.encode(docs, normalize_embeddings=True)

# 4.计算余弦相似度
scores = np.dot(doc_embs, query_emb.T)

# 5.输出结果
for doc, score in zip(docs, scores):
    print(f"相似度:{score:.4f}  文本:{doc}")

# 取得分最高一条
best_idx = np.argmax(scores)
print("\n=====最匹配结果=====")
print(docs[best_idx], f"分数：{scores[best_idx]:.4f}")
