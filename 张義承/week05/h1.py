from sentence_transformers import SentenceTransformer

# 必备库，基于transformers，用途是做模型推理、sbert训练过程的用途
# sentence_transformers 作者 就是 sbert论文 的作者

sentences = ["我喜欢机器学习", "我喜欢深度学习", "我今天心情很不错"]  # 768 512

# modelscope download --model BAAI/bge-small-zh-v1.5  --local_dir BAAI/bge-small-zh-v1.5
# https://huggingface.co/spaces/mteb/leaderboard
model = SentenceTransformer(
    "../../../models/BAAI/bge-small-zh-v1.5/"
)  # sentence-bert 微调之后的
embeddings = model.encode(sentences)
print(embeddings.shape)

similarities = model.similarity(embeddings, embeddings)
print(similarities)

# ========== 文本检索（bge 模型） ==========
# 待检索的文本：用户提问
query = "我今天很开心"
# 文本库：上面的 sentences，向量已缓存在 embeddings 里（提前对库做一次编码）
db_sentences = sentences

# 对 query 编码。bge 官方建议给"查询"加检索指令前缀，效果更好
query_embedding = model.encode([query])

# query 与文本库逐条算相似度
sims = model.similarity(query_embedding, embeddings)

print("\n===== 检索结果（bge-small-zh-v1.5） =====")
print("query:", query)
for i in sorted(range(len(db_sentences)), key=lambda j: sims[0][j], reverse=True):
    print(f"  {float(sims[0][i]):.4f}  {db_sentences[i]}")
print("最相似文本:", db_sentences[int(sims[0].argmax())])

"""
文本库有 200 个样本
用户有2个提问
任务： 在文本库中找到与用户提问相似的样本

BERT NSP： 句子1 和 句子2  拼接为一个输入， 送到bert 提取特征，做分类
SBERT： 分别对 句子1 句子2 提取特征，计算相似度

如果没有任何提前操作：
- BERT NSP： 2 个提问 * 200待选文本 -》 400 BERT 正向传播
- SBERT： 2提问，200待选文本 -》 202 BERT 正向传播

提前对文本库提取特征：
- BERT NSP： 2 个提问 * 200待选文本 -》 400 BERT 正向传播
- SBERT： 2提问 -》 2 BERT 正向传播
"""
