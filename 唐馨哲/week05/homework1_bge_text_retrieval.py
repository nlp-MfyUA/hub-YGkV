"""
第五周作业1: 使用 sentence-transformer 库和 bge 模型进行文本检索
模型: BAAI/bge-small-zh-v1.5
"""

from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# 模型目录
MODEL_PATH = "BAAI/bge-small-zh-v1.5"

# 待检索文本
query_text = "我今天很开心"

# 数据库文本
database_texts = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]


def load_model(model_path: str):
    """加载 bge 模型"""
    print(f"正在加载模型: {model_path}")
    model = SentenceTransformer(model_path)
    print("模型加载完成!")
    return model


def encode_texts(model, texts):
    """将文本编码为向量"""
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings


def retrieve(model, query, database, top_k=3):
    """
    文本检索：根据查询文本从数据库中检索最相似的文本

    Args:
        model: SentenceTransformer模型
        query: 查询文本
        database: 数据库文本列表
        top_k: 返回前k个最相似的结果

    Returns:
        检索结果列表，每个元素为(文本, 相似度)
    """
    # 编码查询文本和数据库文本
    query_embedding = model.encode([query], normalize_embeddings=True)
    database_embeddings = model.encode(database, normalize_embeddings=True)

    # 计算余弦相似度
    similarities = cosine_similarity(query_embedding, database_embeddings)[0]

    # 获取相似度排序（从高到低）
    sorted_indices = np.argsort(similarities)[::-1]

    # 返回top_k结果
    results = []
    for i in sorted_indices[:top_k]:
        results.append({
            "text": database[i],
            "similarity": float(similarities[i])
        })

    return results


def main():
    print("=" * 50)
    print("作业1: BGE 文本检索")
    print("=" * 50)

    # 加载模型
    try:
        model = load_model(MODEL_PATH)
    except Exception as e:
        print(f"模型加载失败: {e}")
        print("\n请先下载模型:")
        print("modelscope download --model BAAI/bge-small-zh-v1.5 --local_dir BAAI/bge-small-zh-v1.5")
        return

    # 显示待检索文本和数据库
    print(f"\n待检索文本: {query_text}")
    print(f"数据库文本: {database_texts}")

    # 执行检索
    print("\n正在执行检索...")
    results = retrieve(model, query_text, database_texts)

    # 显示结果
    print("\n检索结果 (按相似度从高到低排序):")
    print("-" * 50)
    for i, result in enumerate(results, 1):
        print(f"第{i}名: {result['text']}")
        print(f"      相似度: {result['similarity']:.4f}")
        print()

    # 演示：直接计算相似度
    print("=" * 50)
    print("额外演示: 获取查询文本的向量表示")
    query_vec = model.encode([query_text], normalize_embeddings=True)
    print(f"查询文本向量维度: {query_vec.shape}")
    print(f"查询文本向量(前5维): {query_vec[0][:5]}")


if __name__ == "__main__":
    main()