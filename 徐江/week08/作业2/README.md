# 深度研究助手 (Deep Research Assistant)

> 基于 FastAPI + Agent + Embedding 的自动化深度研究报告生成服务

从输入研究主题到自动输出结构化研究报告的全流程自动化，采用大模型进行智能决策，Embedding 进行语义相似度检索与重排序。

## 功能特性

- **Agent 智能决策**：使用 LLM 进行子问题拆解、检索质量评估、补检判断
- **多轮迭代研究**：「规划 - 检索 - 评估 - 补检 - 生成」的迭代式闭环流程
- **语义相似度检索**：基于 Embedding 实现查询与结果的语义匹配和重排序
- **来源追溯**：每条结论关联对应的网页 URL、标题、站点
- **置信度标注**：标注每条结论的可靠程度和信息截止时间
- **断点续研**：支持研究过程数据持久化，中途可继续研究
- **RESTful API**：基于 FastAPI 的 Web 服务接口

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Web 服务                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   POST /api/v1/research          GET  /api/v1/research/{id}    │
│        │                              │                         │
│        ▼                              ▼                         │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                   Agent 智能决策层                       │   │
│   │  ┌─────────────┐              ┌─────────────┐          │   │
│   │  │ Planning    │              │ Evaluator   │          │   │
│   │  │ Agent       │              │ Agent       │          │   │
│   │  │ (问题拆解)  │              │ (质量评估)  │          │   │
│   │  └─────────────┘              └─────────────┘          │   │
│   └─────────────────────────────────────────────────────────┘   │
│        │                                                         │
│        ▼                                                         │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │               Embedding 相似度检索层                     │   │
│   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │   │
│   │  │ Encoder     │  │ VectorStore │  │ Reranker    │     │   │
│   │  │ (向量化)    │  │ (向量存储)  │  │ (重排序)    │     │   │
│   │  └─────────────┘  └─────────────┘  └─────────────┘     │   │
│   └─────────────────────────────────────────────────────────┘   │
│        │                                                         │
│        ▼                                                         │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                      大模型 (LLM)                         │   │
│   │         子问题拆解 · 内容理解 · 报告生成                  │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 产品输出

1. **结构化研究报告**：研究摘要、分节正文、关键结论、遗留问题
2. **来源列表**：网页 URL、标题、站点名称
3. **研究过程记录**：检索关键词、已读页面、迭代轮次
4. **置信度说明**：可靠程度、信息截止时间

## 项目结构

```
week08/
├── README.md                     # 项目说明文档
├── pyproject.toml                # 项目配置
├── uv.lock                       # 依赖锁定
│
├── app/                          # 应用主目录
│   ├── __init__.py
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # 配置加载模块
│   │
│   ├── api/                      # API 路由层
│   │   └── routes/
│   │       └── research.py       # 研究接口路由
│   │
│   ├── core/                     # 核心业务逻辑
│   │   ├── agent/
│   │   │   ├── planner.py        # 主题规划 Agent
│   │   │   └── evaluator.py      # 检索质量评估 Agent
│   │   ├── search/
│   │   │   ├── client.py         # Web 搜索客户端
│   │   │   └── retrier.py        # 重试机制
│   │   ├── embedding/
│   │   │   ├── encoder.py        # Embedding 编码器
│   │   │   ├── vector_store.py   # 向量存储
│   │   │   └── reranker.py       # 重排序器
│   │   └── llm/
│   │       └── client.py         # 大模型客户端
│   │
│   ├── services/                 # 业务服务层
│   │   ├── research_service.py   # 研究主服务
│   │   └── report_service.py     # 报告生成服务
│   │
│   └── models/                   # 数据模型
│       ├── request.py            # 请求模型
│       └── response.py           # 响应模型
│
├── config/                       # 配置文件目录
│   └── settings.yaml             # 主配置文件
│
└── data/                         # 数据存储目录
    ├── research/                 # 研究数据
    └── vectors/                  # 向量数据
```

## 安装部署

### 1. 安装依赖

```bash
# 使用 uv 安装（推荐）
uv pip install -r requirements.txt

# 或使用 pip
pip install -r requirements.txt
```

### 2. 环境配置

创建 `config/settings.yaml` 配置文件：

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  reload: true

api:
  # Web 搜索 API（博查）
  web_search:
    base_url: "https://api.bocha.cn/v1/web-search"
    api_key: "${BOCHA_API_KEY}"  # 从环境变量读取
    timeout: 30
    max_retries: 3

  # 大模型 API
  llm:
    provider: "openai"  # openai / anthropic / glm
    api_key: "${LLM_API_KEY}"
    model: "gpt-4o-mini"

  # Embedding
  embedding:
    provider: "openai"
    model: "text-embedding-3-small"

search:
  max_iterations: 3           # 最大迭代轮次
  rerank_threshold: 0.7       # 重排序阈值
  similarity_threshold: 0.6   # 相似度阈值
```

### 3. 设置环境变量

```bash
# Linux/Mac
export BOCHA_API_KEY="your_bocha_api_key"
export LLM_API_KEY="your_llm_api_key"

# Windows (PowerShell)
$env:BOCHA_API_KEY="your_bocha_api_key"
$env:LLM_API_KEY="your_llm_api_key"
```

### 4. 启动服务

```bash
# 开发模式
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

## API 使用说明

### 1. 创建研究任务

```bash
curl -X POST "http://localhost:8000/api/v1/research" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "人工智能在医疗领域的应用现状",
    "max_iterations": 3
  }'
```

响应：
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "研究任务已创建"
}
```

### 2. 查询研究进度

```bash
curl -X GET "http://localhost:8000/api/v1/research/550e8400-e29b-41d4-a716-446655440000"
```

### 3. 获取研究报告

```bash
curl -X GET "http://localhost:8000/api/v1/research/550e8400-e29b-41d4-a716-446655440000/report"
```

## 研究流程

```
1. 主题规划 (Planning Agent)
   └─ 将研究主题拆解为 3-5 个子问题

2. 多轮检索 (Multi-Round Retrieval Loop)
   ├─ 关键词搜索 → Web 搜索 API
   ├─ 内容抽取 → 提取网页信息
   ├─ Embedding 编码 → 向量化
   ├─ 相似度计算 + 重排序
   └─ Agent 评估 → 判断是否需要补检
        ├─ 分数 >= 阈值: 退出循环
        └─ 分数 < 阈值: 补充检索

3. 报告生成 (LLM)
   └─ 整合内容 → 生成结构化 Markdown 报告
```

## 检索与重排序机制

```
关键词查询
      │
      ▼
┌─────────────────┐
│  Web搜索API    │  → 返回网页列表
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  内容抽取       │  → 标题、摘要、内容
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Embedding编码  │  → 向量化
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  相似度计算    │  → 余弦相似度
│  + 重排序      │  → 按分数排序
└────────┬────────┘
         │
         ▼
    排序结果
         │
         ▼
┌─────────────────┐
│  Agent评估      │  → 质量判断
└─────────────────┘
```

## 输出示例

研究报告包含以下固定模块：

- **研究摘要**：主题概述和主要发现
- **分节正文**：按子问题分节的详细内容（含来源标注）
- **关键结论**：研究的主要结论 + 置信度 + 来源
- **遗留问题**：未解决或需进一步研究的问题
- **来源列表**：所有引用的网页信息

所有非常识性结论都标注对应的来源编号，如 `[1][2]`，并标注置信度等级。

## API 服务商

- **Web 搜索**：博查 AI 搜索 ([bocha.cn](https://www.bocha.cn/))
- **大模型**：OpenAI GPT / Anthropic Claude / 智谱 GLM
- **Embedding**：OpenAI Embedding

## 许可证

MIT License