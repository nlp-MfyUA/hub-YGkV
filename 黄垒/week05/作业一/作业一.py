from sentence_transformers import SentenceTransformer

BGE_MODEL_PATH = "D:\\Works\\agent_codes\\models\\BAAI\\bge-small-zh-v1.5"
# 待检索数据
sentences = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]


model = SentenceTransformer(BGE_MODEL_PATH)
embeddings = model.encode(sentences)

while True:
    query = input("请输入查询语句：")
    if query == "exit":
        break
    query_embedding = model.encode([query])
    similarities = model.similarity(query_embedding, embeddings)
    print(similarities)
    print(sentences[similarities.argmax()])