import json
import time
from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer

# 替换为你的 Elasticsearch 地址
es = Elasticsearch("http://localhost:9200")

# 1. 生成向量: 加载预训练模型
# 这个模型可以将句子转换为 768 维的向量
print("正在加载 SentenceTransformer 模型...")
model = SentenceTransformer('../models/BAAI/bge-small-zh-v1.5')
print("模型加载完成。")

# --- 2. 创建索引和向量字段 ---
index_name = "semantic_search_demo"

# 检查索引是否存在，如果不存在则创建
if es.indices.exists(index=index_name):
    es.indices.delete(index=index_name)
    print(f"旧索引 '{index_name}' 已删除。")

print(f"正在创建新索引 '{index_name}'...")
es.indices.create(
    index=index_name,
    body={
        "mappings": {
            "properties": {
                "text": {"type": "text"},
                "text_vector": {
                    "type": "dense_vector",
                    "dims": 512,  # 根据模型的输出维度来设置
                    "index": True,
                    "similarity": "cosine"
                }
            }
        }
    }
)
print(f"索引 '{index_name}' 创建成功。")

# --- 3. 插入带有向量的文档 ---
print("\n正在生成并插入文档...")
documents = [
    "人工智能是未来的趋势。",
    "机器学习是人工智能的一个重要分支。",
    "自然语言处理技术让机器理解人类语言。",
    "今天天气真好，适合出去玩。",
    "工程技术需要画图。",
    "我最喜欢的运动是篮球和足球。"
]

for doc_text in documents:
    # 生成向量
    vector = model.encode(doc_text).tolist()

    # 插入文档
    es.index(
        index=index_name,
        document={
            "text": doc_text,
            "text_vector": vector
        }
    )
print("所有文档插入完成。")

# 刷新索引
es.indices.refresh(index=index_name)
time.sleep(1)  # 等待索引刷新

# --- 4. 执行向量检索 ---
print("\n--- 执行向量检索 ---")
query_text = "关于AI和未来的技术"

# 将查询文本转换为向量
query_vector = model.encode(query_text).tolist()

# 使用 knn 查询进行向量检索
response = es.search(
    index=index_name,
    body={
        "knn": {
            "field": "text_vector",
            "query_vector": query_vector,
            "k": 3,
            "num_candidates": 10
        },
        "fields": ["text"],  # 返回 text 字段
        "_source": False  # 不返回整个文档源
    }
)

# 打印结果
print(f"查询文本: '{query_text}'")
print(f"找到 {response['hits']['total']['value']} 个最相关的结果:")

for hit in response['hits']['hits']:
    score = hit['_score']
    text = hit['fields']['text'][0]
    print(f"得分: {score:.4f}, 内容: {text}")

# 也可以将 knn 查询与其他过滤器结合使用
# 比如，只在包含特定关键词的文档中进行向量搜索
print("\n--- 结合 knn 和 filter 查询 ---")
response_combined = es.search(
    index=index_name,
    body={
        "knn": {
            "field": "text_vector",
            "query_vector": query_vector,
            "k": 3,
            "num_candidates": 10
        },
        "query": {
            "match": {
                "text": "技术"
            }
        },
        "fields": ["text"],
        "_source": False
    }
)

print(f"查询文本: '{query_text}' (并过滤包含 '技术' 的文档)")
print(f"找到 {response_combined['hits']['total']['value']} 个最相关的结果:")

for hit in response_combined['hits']['hits']:
    score = hit['_score']
    text = hit['fields']['text'][0]
    print(f"得分: {score:.4f}, 内容: {text}")


print("\n--- 结合 knn 和 filter 查询 ---")
response_combined = es.search(
    index=index_name,
    body={
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "text": "技术"
                        }
                    }
                ],
                "filter": [
                    {
                        "knn": {
                            "field": "text_vector",
                            "query_vector": query_vector,
                            "k": 10,
                            "num_candidates": 10
                        }
                    }
                ]
            }
        },
        "fields": ["text"],
        "_source": False
    }
)

print(f"查询文本: '{query_text}' (并过滤包含 '技术' 的文档)")
print(f"找到 {response_combined['hits']['total']['value']} 个最相关的结果:")

for hit in response_combined['hits']['hits']:
    score = hit['_score']
    text = hit['fields']['text'][0]
    print(f"得分: {score:.4f}, 内容: {text}")