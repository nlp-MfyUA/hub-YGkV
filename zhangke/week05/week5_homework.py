from sentence_transformers import SentenceTransformer

model = SentenceTransformer("../../modelscope/bge/BAAI/bge-small-zh-v1.5/")
sentences = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]
sentenceTarget = ["我今天很开心"]
embeddingTarget = model.encode(sentenceTarget)
embeddings = model.encode(sentences)
similarities = model.similarity(embeddings, embeddingTarget)
print(similarities)


