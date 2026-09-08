# -*- coding: utf-8 -*-
"""
PageIndex 本地文档解析与问答脚本
依赖：pip install -U pageindex
环境变量：export DEEPSEEK_API_KEY="your-api-key"
"""
import os
from pageindex import PageIndexClient

def main():
    # 初始化客户端（优先从环境变量读取 DEEPSEEK_API_KEY）
    client = PageIndexClient(
        index_model="deepseek/deepseek-chat",  # 构建 tree 使用的模型
        chat_model="deepseek/deepseek-chat",   # 问答使用的模型
        storage_path=".pageindex",
    )

    doc_path = "资料/数据库.pdf"
    print(f"正在提交并解析文档: {doc_path}")
    
    # 建立 PageIndex（离线解析，单文档只需执行一次）
    result = client.submit_document(doc_path)
    doc_id = result.get("doc_id")
    print(f"解析完成，doc_id: {doc_id}")

    # 获取并打印 Tree Index 结构
    tree = client.get_document_structure(doc_id)
    print("\n--- 文档树结构 (Tree Index) ---")
    print(tree)

    # 基于 Tree Index 进行问答
    query = "数据库的四个核心概念是什么？"
    print(f"\n提问: {query}")
    answer = client.chat(
        query,
        doc_id=doc_id,
        reasoning_effort="high",
    )
    print("\n--- 回答结果 ---")
    print(answer)

if __name__ == "__main__":
    main()
