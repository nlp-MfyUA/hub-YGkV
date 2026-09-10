# 深度研究助手 (Deep Research Assistant)

> 基于 FastAPI + Agent + Embedding 的自动化深度研究报告生成服务

## 项目概述

本项目是一个工程化的深度研究助手后端服务，采用 FastAPI 框架构建 RESTful API，运用 Agent 进行智能决策（子问题拆解、多轮检索判断），通过 Embedding 实现语义相似度检索与重排序，最终由大模型完成结构化研究报告的生成。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              深度研究助手架构                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                 │
│   │   FastAPI   │────▶│    Agent    │────▶│   Embedding │                 │
│   │   Web服务   │     │   智能决策  │     │ 相似度检索  │                 │
│   └─────────────┘     └─────────────┘     └─────────────┘                 │
│         │                   │                   │                         │
│         ▼                   ▼                   ▼                         │
│   ┌─────────────────────────────────────────────────────────────────┐     │
│   │                       大模型 (LLM)                               │     │
│   │  - 子问题拆解                                                    │     │
│   │  - 内容理解与抽取                                                │     │
│   │  - 报告生成与整合                                                │     │
│   └─────────────────────────────────────────────────────────────────┘     │
│                                 │                                           │
│                                 ▼                                           │
│   ┌─────────────────────────────────────────────────────────────────┐     │
│   │                     外部 Services                                │     │
│   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │     │
│   │  │  Web搜索API │  │ EmbeddingAPI │  │  大模型API (OpenAI/    │ │     │
│   │  │  (博查)     │  │  (向量存储)   │  │  Claude/glm等)         │ │     │
│   │  └─────────────┘  └─────────────┘  └─────────────────────────┘ │     │
│   └─────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 业务流程

```
用户请求 (研究主题)
       │
       ▼
┌────────────────────────────────────────────────────────────────┐
│  Planning Agent - 主题规划                                     │
│  • 使用LLM将研究主题拆解为3-5个子问题                         │
│  • 生成首轮检索关键词清单                                     │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Multi-Round Retrieval - 多轮检索循环                         │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  1. 关键词搜索 (调用Web搜索API)                          │ │
│  │  2. Embedding编码 + 相似度检索与重排序                   │ │
│  │  3. 质量评估 (Agent判断是否需要补充检索)                 │ │
│  │     - 分数 >= 阈值: 退出循环                             │ │
│  │     - 分数 < 阈值: 生成补充关键词，繼續检索              │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  LLM Report Generation - 大模型报告生成                       │
│  • 整合重排序后的内容                                         │
│  • 生成结构化Markdown报告                                     │
│  • 标注来源、置信度                                           │
└────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                   API Response (JSON)
```

## 项目结构

```
week08/
├── CLAUDE.md                     # 项目说明文档（本文件）
├── README.md                     # 项目README
├── pyproject.toml                # 项目配置
├── uv.lock                       # 依赖锁定
│
├── app/                          # 应用主目录
│   ├── __init__.py
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # 配置加载模块
│   │
│   ├── api/                      # API 路由层
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       └── research.py       # 研究接口路由
│   │
│   ├── core/                     # 核心业务逻辑
│   │   ├── __init__.py
│   │   ├── agent/
│   │   │   ├── __init__.py
│   │   │   ├── planner.py        # 主题规划Agent
│   │   │   └── evaluator.py      # 检索质量评估Agent
│   │   ├── search/
│   │   │   ├── __init__.py
│   │   │   ├── client.py         # Web搜索客户端
│   │   │   └── retrier.py        # 重试机制
│   │   ├── embedding/
│   │   │   ├── __init__.py
│   │   │   ├── encoder.py        # Embedding编码器
│   │   │   ├── vector_store.py   # 向量存储
│   │   │   └── reranker.py       # 重排序器
│   │   └── llm/
│   │       ├── __init__.py
│   │       └── client.py         # 大模型客户端
│   │
│   ├── services/                 # 业务服务层
│   │   ├── __init__.py
│   │   ├── research_service.py   # 研究主服务
│   │   └── report_service.py     # 报告生成服务
│   │
│   ├── models/                   # 数据模型
│   │   ├── __init__.py
│   │   ├── request.py            # 请求模型
│   │   └── response.py           # 响应模型
│   │
│   └── utils/                    # 工具函数
│       ├── __init__.py
│       ├── logger.py             # 日志工具
│       └── storage.py            # 数据持久化
│
├── config/                       # 配置文件目录
│   └── settings.yaml             # 主配置文件
│
├── data/                         # 数据存储目录
│   ├── research/                 # 研究数据
│   └── vectors/                  # 向量数据
│
└── tests/                        # 测试目录
    └── ...
```

## 核心模块说明

### 1. app/main.py - FastAPI 应用入口
- FastAPI 应用初始化
- 中间件配置（CORS、请求日志等）
- 路由注册
- 启动配置

### 2. app/config.py - 配置加载模块
- 加载 `config/settings.yaml` 外部配置文件
- 环境变量覆盖支持
- 提供配置项访问接口
- 外部配置文件结构：

```yaml
# config/settings.yaml
server:
  host: "0.0.0.0"
  port: 8000
  reload: true

api:
  # Web搜索API配置
  web_search:
    base_url: "https://api.bocha.cn/v1/web-search"
    api_key: "${BOCHA_API_KEY}"  # 从环境变量读取
    timeout: 30
    max_retries: 3
    count: 10
    freshness: "oneYear"

  # 大模型API配置
  llm:
    provider: "openai"  # openai / anthropic / glm
    api_key: "${LLM_API_KEY}"
    model: "gpt-4o-mini"
    temperature: 0.7
    max_tokens: 4000

  # Embedding配置
  embedding:
    provider: "openai"  # openai / mteb
    api_key: "${LLM_API_KEY}"
    model: "text-embedding-3-small"
    dimension: 1536

# 搜索配置
search:
  max_iterations: 3           # 最大迭代轮次
  min_sources_per_subtopic: 2 # 每个子问题最少来源数
  rerank_threshold: 0.7       # 重排序阈值
  similarity_threshold: 0.6   # 相似度阈值

# 报告配置
report:
  output_dir: "data/research"
  include_timestamps: true
  confidence_levels:
    high: "信息来源可靠，多源验证"
    medium: "信息来源较可靠，单一来源或推断"
    low: "信息来源有限，模型推断"

# 日志配置
logging:
  level: "INFO"
  file: "logs/research.log"
```

### 3. app/core/agent/ - Agent 智能决策模块

#### planner.py - 主题规划 Agent
- **功能**：使用 LLM 将研究主题拆解为 3-5 个子问题
- **输入**：用户研究主题
- **输出**：子问题列表 + 首批检索关键词
- **Prompt 示例**：
```
请将以下研究主题拆解为3-5个具体的子问题，并给出每个子问题的检索关键词。
研究主题：{topic}

请按以下JSON格式返回：
{
  "subtopics": [{"id": 1, "question": "...", "keywords": ["...", "..."]}],
  "reasoning": "拆解理由"
}
```

#### evaluator.py - 检索质量评估 Agent
- **功能**：评估当前检索结果是否满足研究需求
- **输入**：子问题列表 + 当前检索结果 + 质量分数
- **输出**：是否需要继续检索 + 补充关键词（若需要）
- **决策逻辑**：基于重排序分数判断是否需要补检

### 4. app/core/search/ - 搜索模块

#### client.py - Web搜索客户端
- 调用博查 Web 搜索 API
- 请求参数：`query`, `summary`, `freshness`, `count`
- 返回结果：网页标题、链接、摘要、站点、发布时间
- 异常处理：最多 3 次重试，失败后标记页面不可读

#### retrier.py - 重试机制
- 指数退避策略
- 记录重试日志
- 统计重试次数

### 5. app/core/embedding/ - Embedding 相似度检索模块

#### encoder.py - Embedding 编码器
- 使用指定Embedding模型编码文本
- 支持批量编码
- 返回向量表示

#### vector_store.py - 向量存储
- 存储检索结果的向量表示
- 支持增量添加
- 提供向量检索接口

#### reranker.py - 重排序器
- **功能**：计算查询与检索结果之间的语义相似度
- **方法**：
  1. 对检索结果使用 Embedding 编码
  2. 计算与查询的余弦相似度
  3. 按相似度分数重排序
- **输出**：带分数的排序结果列表

### 6. app/core/llm/ - 大模型客户端
- 统一的 LLM 调用接口
- 支持多种 Provider（OpenAI / Anthropic / GLM）
- 流式输出支持
- 超时和错误处理

### 7. app/services/ - 业务服务层

#### research_service.py - 研究主服务
- 协调各模块完成完整研究流程
- 状态管理：规划 → 检索 → 评估 → 生成
- 进度保存与恢复（断点续研）

#### report_service.py - 报告生成服务
- 整合重排序后的内容
- 调用 LLM 生成结构化 Markdown 报告
- 报告结构：研究摘要、分节正文、关键结论、遗留问题
- 标注来源编号和置信度

### 8. app/api/routes/research.py - API 路由
- `POST /api/v1/research` - 创建研究任务
- `GET /api/v1/research/{task_id}` - 获取研究进度
- `GET /api/v1/research/{task_id}/report` - 获取研究报告
- `DELETE /api/v1/research/{task_id}` - 取消研究任务

## API 接口规范

### 1. 创建研究任务
```
POST /api/v1/research
Content-Type: application/json

Request:
{
  "topic": "研究主题",
  "max_iterations": 3,          // 可选，默认3
  "options": {
    "language": "zh-CN",        // 可选
    "include_raw_sources": false // 可选，是否返回原始来源
  }
}

Response:
{
  "task_id": "uuid",
  "status": "pending",
  "message": "研究任务已创建"
}
```

### 2. 获取研究进度
```
GET /api/v1/research/{task_id}

Response:
{
  "task_id": "uuid",
  "status": "processing" | "completed" | "failed",
  "progress": {
    "current_step": 2,
    "total_steps": 5,
    "subtopics_completed": 2,
    "total_subtopics": 4
  },
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:01:00Z"
}
```

### 3. 获取研究报告
```
GET /api/v1/research/{task_id}/report

Response:
{
  "task_id": "uuid",
  "status": "completed",
  "report": {
    "summary": "## 研究摘要\n...",
    "sections": [...],
    "conclusions": [...],
    "remaining_issues": [...]
  },
  "sources": [
    {
      "id": 1,
      "title": "网页标题",
      "url": "https://...",
      "site_name": "站点名称",
      "published_date": "2024-01-01"
    }
  ],
  "metadata": {
    "total_iterations": 2,
    "total_sources": 15,
    "generated_at": "2024-01-01T00:05:00Z"
  }
}
```

## 检索与重排序流程

```
关键词查询
    │
    ▼
┌─────────────────┐
│  Web搜索API    │ ← 返回原始网页列表
│  (博查)        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  内容抽取      │ ← 提取网页标题、摘要、内容
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Embedding编码  │ ← 将每个网页内容编码为向量
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  相似度计算    │ ← 计算查询与各网页的余弦相似度
│  + 重排序      │ ← 按分数从高到低排列
└────────┬────────┘
         │
         ▼
    排序结果列表
         │
         ▼
┌─────────────────┐
│  Agent评估      │ ← 判断是否需要补充检索
│  (Evaluator)    │   - 分数 >= 阈值: 结束
│                 │   - 分数 < 阈值: 补充检索
└─────────────────┘
```

## 质量评估与补检机制

### Agent 评估决策伪代码
```python
def evaluate_retrieval(subtopics, ranked_results):
    """
    评估当前检索结果是否充足
    返回: (needs_more_search: bool, additional_keywords: list)
    """

    # 计算每个子问题的平均分数
    scores = []
    for subtopic in subtopics:
        top_results = ranked_results[subtopic.id][:3]
        avg_score = sum(r.score for r in top_results) / len(top_results)
        scores.append(avg_score)

    overall_score = sum(scores) / len(scores)

    # 判断是否需要补充检索
    if overall_score >= RERANK_THRESHOLD:
        return False, []  # 检索充足，结束
    else:
        # 生成补充关键词
        additional_keywords = generate_supplement_keywords(subtopics, ranked_results)
        return True, additional_keywords
```

## 输出格式

### 研究报告结构
```markdown
# {研究主题}

## 研究摘要
{研究主题的概述和主要发现}

## 分节正文
### 1. {子问题1}
{详细内容，包含来源标注[1][2]}

### 2. {子问题2}
{详细内容，包含来源标注[3][4]}

...

## 关键结论
1. {结论1} [置信度: 高 来源: 1,2]
2. {结论2} [置信度: 中 来源: 3]

## 遗留问题
- {问题1}
- {问题2}

## 来源列表
1. [标题](url) - 站点名称 - 发布日期
2. [标题](url) - 站点名称 - 发布日期
```
- 每条非常识性结论标注对应的来源编号
- 标注置信度等级（高/中/低）
- 遗留问题标注需要进一步研究的方向

## 部署与运行

### 开发模式
```bash
# 安装依赖
uv pip install -r requirements.txt

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 生产模式
```bash
# 使用 gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Docker 部署
```bash
docker build -t deep-research-assistant .
docker run -p 8000:8000 \
  -e BOCHA_API_KEY=your_key \
  -e LLM_API_KEY=your_key \
  deep-research-assistant
```

## 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `BOCHA_API_KEY` | 博查搜索API密钥 | 是 |
| `LLM_API_KEY` | 大模型API密钥 | 是 |
| `LOG_LEVEL` | 日志级别 | 否 |
| `DATA_DIR` | 数据存储目录 | 否 |

## 技术栈

- **Web框架**: FastAPI
- **异步Runtime**: Uvicorn
- **LLM**: OpenAI GPT / Anthropic Claude / 智谱GLM
- **Embedding**: OpenAI Embedding / MTEB
- **配置**: PyYAML
- **日志**: Loguru
- **数据存储**: SQLite / JSON文件
- **HTTP客户端**: httpx / requests