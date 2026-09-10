from sentence_transformers import SentenceTransformer
from typing import List
import numpy as np

# 数据库文本
database_text = ["我喜欢机器学习", "我喜欢深度学习", "我今天心情很不错"]

# 获取模型
model = SentenceTransformer('BAAI/bge-small-zh-v1.5')

# 进行数据库嵌入
database_embeddings = model.encode(database_text, device='cuda', normalize_embeddings=True, batch_size=32)
print(database_embeddings.shape)


# 计算数据库中最相似度的文本所在数据库的下标
def most_similarity(text: str|List[str]) -> List[int]:
    if isinstance(text, str):
        text = [text]

    # [n, 512]
    embeddings = model.encode(text, device='cuda', normalize_embeddings=True, batch_size=32)

    # 计算相似度 [n, 512] * [3, 512] = [n, 3]
    similarities = model.similarity(embeddings, database_embeddings).detach().cpu().numpy()

    # 计算每一行的最大值下标
    row_max_indices = np.argmax(similarities, axis=1).tolist()

    return row_max_indices


# 打印结果
def print_result(query_texts: str|List[str], index_list: List[int]) -> None:
    if isinstance(query_texts, str):
        query_texts = [query_texts]

    print("检索结果为：")
    for text, index in zip(query_texts,index_list):
        print(f"搜索：{text}，最相似结果为：{database_text[index]}")



if __name__ == "__main__":
    # 待检测文本
    input_text = "我今天很开心"
    result = most_similarity(input_text)
    print_result(input_text, result)

    # 待检测文本
    input_text = ["深度学习", "机器学习", "我爱吃苹果"]
    result = most_similarity(input_text)
    print_result(input_text, result)

