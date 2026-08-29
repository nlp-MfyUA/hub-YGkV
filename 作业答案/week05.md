## task1

```
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import os

# 加载模型
model_path = r"BAAI--bge-small-zh-v1.5"
model = SentenceTransformer(model_path)

# 语料
corpus = ["我喜欢机器学习", "我喜欢深度学习", "我今天心情很不错"]
corpus_emb = model.encode(corpus, normalize_embeddings=True)

# 搜索函数
def search(q, top_k=1):
    q_emb = model.encode("为这个句子生成表示以用于检索相关文章：" + q, normalize_embeddings=True)
    scores = cosine_similarity([q_emb], corpus_emb)[0]
    idx = scores.argsort()[-top_k:][::-1]
    return [(corpus[i], float(scores[i])) for i in idx]

# 测试
for q in ["我今天很开心", "机器学习"]:
    text, score = search(q)[0]
    print(f"查询: {q} → {text} (相似度: {score:.4f})")
```

## task2 

Ollama 是一个用于在本地电脑或服务器上运行大语言模型的工具。它把模型下载、模型管理、推理运行、GPU/CPU 调度以及 API 服务等过程进行了封装，让开发者不需要直接处理复杂的模型加载和推理环境，就能够快速运行 Qwen、Llama、DeepSeek、Gemma 等开源模型。

Ollama 最大的特点是本地运行简单。对于学习 AI 应用开发的人来说，可以不用购买模型 API，就能够在自己的电脑上完成 Prompt、RAG、Agent、Tool Calling 等实验。同时，因为数据不必发送到第三方模型服务，本地运行也比较适合一些对数据隐私要求较高的场景。

```
# 查看 Ollama 版本
ollama --version

# 查看 Ollama 帮助
ollama --help

# 下载模型
ollama pull qwen3

# 直接运行模型并进入交互式对话
ollama run qwen3

# 查看本地已经下载的模型
ollama list

# 查看当前正在运行、占用内存或显存的模型
ollama ps

# 停止正在运行的模型
ollama stop qwen3

# 删除本地模型
ollama rm qwen3

# 启动 Ollama API 服务
# 默认监听：http://localhost:11434
ollama serve

# 使用 curl 调用 Ollama 的模型生成 API
curl http://localhost:11434/api/generate -d '{
  "model": "qwen3",
  "prompt": "什么是 RAG？",
  "stream": false
}'

# 查看 Ollama 当前提供的模型列表 API
curl http://localhost:11434/api/tags
```
