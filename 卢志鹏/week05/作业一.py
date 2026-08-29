from sentence_transformers import SentenceTransformer
# 必备库，基于transformers，用途是做模型推理、sbert训练过程的用途
# sentence_transformers 作者 就是 sbert论文 的作者

sentences = [
    "我喜欢机器学习", # 768 512
    "我喜欢深度学习",
    "我今天心情很不错"
]

# modelscope download --model BAAI/bge-small-zh-v1.5  --local_dir BAAI/bge-small-zh-v1.5
# 加载模型
model = SentenceTransformer(r"E:\models\google-bert\bge-small-zh-v1.5") # sentence-bert 微调之后的

def find_most_similar(query: str, sentence_list: list[str], encoder: SentenceTransformer) -> str:
    """传入字符串，返回 sentence_list 中与 query 语义最相近的句子。

    思路：提前对句子库提取特征并缓存，查询时只对 query 编码一次，
    再与库向量计算余弦相似度，取最大值对应的句子。
    """
    # 提前对文本库提取特征（以库的 id 为键做缓存，避免重复编码）
    if not hasattr(find_most_similar, "_cache"):
        find_most_similar._cache = {}  # type: ignore[attr-defined]
    cache = find_most_similar._cache  # type: ignore[attr-defined]
    key = id(sentence_list)
    if key not in cache:
        cache[key] = (sentence_list, encoder.encode(sentence_list))

    ref_sentences, ref_embeddings = cache[key]

    # 对查询字符串编码：[1, dim] -> [dim]
    query_embedding = encoder.encode([query])[0]
    # print(f"query_embedding: {query}, model.encode([query])[0]:\n {query_embedding}")

    # 与库中每个句子计算余弦相似度，取最相近的下标
    sims = encoder.similarity(query_embedding, ref_embeddings)[0]
    best_idx = int(sims.argmax())
    similarity_radio = sims[best_idx]
    ref_sentence = ref_sentences[best_idx]

    print(f"查询：{query} 与 sentences 中的语义上最相似的句子: {ref_sentence}")
    print(f"model.similarity(query_embedding, embeddings): {sims}")
    print(f"语义相似度相似度比例: {similarity_radio:.4f}")

    return ref_sentence



query = "我今天很开心"
best = find_most_similar(query, sentences, model)
query = "我热爱机器学习技术"
best = find_most_similar(query, sentences, model)
query = "Transformer"
best = find_most_similar(query, sentences, model)
