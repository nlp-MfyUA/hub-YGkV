# Chinook SQL Agent：七阶段完整 Workflow

**Week 11 · Task 1｜课程作业提交版**

本项目基于课程提供的 `sql-agent.ipynb`、Chinook SQLite 数据库与课堂多 Agent 编排思路，完成 **数据库解析 → Table 选择 → SQL 生成 → SQL 校验 → SQL 改写 → SQL 执行 → 结果汇总** 七个阶段，并实现外键 BFS 补表、结构化状态、日志记录和边界测试。

## 1. 项目结构

```text
Chinook_SQL_Agent_提交版/
├── pyproject.toml
├── README.md
├── .env.example
├── ref/
│   └── chinook.db
├── src/sql_agent/
│   ├── __main__.py           # python -m sql_agent
│   ├── cli.py                # 命令行
│   ├── config.py             # 环境变量配置
│   ├── models.py             # Pydantic 数据契约
│   ├── workflow.py           # 七阶段异步编排（核心）
│   ├── logging_config.py
│   ├── agents/
│   │   ├── table_selector.py
│   │   ├── sql_generator.py
│   │   ├── sql_rewriter.py
│   │   └── result_summarizer.py
│   └── db/
│       ├── catalog.py        # SQLite Schema、样例、外键、BFS 补表
│       ├── validator.py      # SQL 只读安全及语法、对象预校验
│       └── executor.py       # 只读执行、行数和超时限制
├── examples/
│   └── offline_demo.py      # 无密钥的模拟端到端运行
├── tests/                    # 完整单元、集成测试
└── docs/
    ├── 设计说明.md
    └── 测试与验收报告.md
```

## 2. 快速开始

**环境：Python 3.10 及以上；可以联网安装依赖。**

```bash
# 在项目目录内
python -m venv .venv
# Linux/macOS：source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1

python -m pip install -e ".[dev]"
```

### 2.1 无 API Key 验收

```bash
python examples/offline_demo.py
python -m pytest -q
```

`offline_demo.py` 明确使用 **Mock LLM（预设输出）**，只证明工作流、数据库读取、验证和自动改写能够协作，**不是通用自然语言选表模型**。

### 2.2 真实模型运行

本提交版与课程参考工程一样，使用 OpenAI Agents SDK，通过兼容 API 连接 DeepSeek。以下是 Linux/macOS 示例：

```bash
export OPENAI_API_KEY="你自己的 DeepSeek API Key"
export OPENAI_BASE_URL="https://api.deepseek.com"
export SQL_AGENT_MODEL="deepseek-flash"
export SQL_AGENT_SUMMARY_MODEL="deepseek-flash"

python -m sql_agent "购买过 Rock 音乐的客户有多少位？"
```

Windows PowerShell：

```powershell
$env:OPENAI_API_KEY = "你自己的 DeepSeek API Key"
$env:OPENAI_BASE_URL = "https://api.deepseek.com"
$env:SQL_AGENT_MODEL = "deepseek-flash"
python -m sql_agent "购买过 Rock 音乐的客户有多少位？"
```

模型和账户需以服务商当前可用配置为准；第三方兼容 API 的结构化输出支持可能因提供商与版本而变化。**没有有效 API Key 不会发起真实模型请求。**

## 3. 七阶段与核心接口

| 阶段 | 实现 |
|---|---|
| 数据库解析 | `SchemaCatalog`（表、列、distinct/missing/min/max/mode、样例、外键） |
| Table 选择 | `TableSelectAgent` + `TableSelection` + 真实表名校验 |
| JOIN 表补全 | `SchemaCatalog.complete_join_tables()`（BFS 图搜索） |
| SQL 生成 | `SQLGeneratorAgent` + `SQLDraft` |
| SQL 校验 | `SQLValidator.validate()`（安全关键字、单条 SQL、EXPLAIN） |
| SQL 改写 | `SQLRewriteAgent` + 失败 SQL/错误码/历史/重试上限 |
| SQL 执行 | `SQLExecutor.execute()`（只读连接、Authorizer、行数、超时） |
| 结果汇总 | `ResultSummaryAgent` + `FinalAnswer`，失败时降级表格 |

`SQLAgentWorkflow.run(question)` 为总入口。流程失败时输出结构化错误，不直接返回未经校验的 SQL 结果。

## 4. 示例问题

可以使用以下问题进行演示：

- “总共有多少张专辑？”
- “购买过 Rock 音乐的客户有多少位？”
- “统计每位歌手拥有的专辑数量，包括没有专辑的歌手。”
- “每种音乐类型的销售额排名如何？”

为了避免幻觉，结果汇总 Agent 只从真实 SQL 查询结果提取事实。SQL 查询结果为空时返回“未查询到符合条件的数据”。

## 5. 安全与限制

- 使用 `mode=ro` + `PRAGMA query_only` + SQLite Authorizer，不允许更新原始 SQLite 数据库。
- 只允许单条只读查询；通过 `EXPLAIN` 检查 SQLite 语法与字段引用，使用最多指定次数的重写。
- 执行器限制运行时间、结果行数以及每个单元格长度。
- **BFS 证明表之间存在外键路径，不保证连接路径符合所有业务含义。**
- **EXPLAIN 成功不能证明 SQL 的业务语义正确**，例如错误 JOIN 可能返回貌似合理的数据。
- 这是一套作业级 SQL Agent，非生产级隔离沙箱；真实业务应采用最小权限账号、资源配额及 SQL AST 语义校验。

## 6. 验收

已在上传的 Chinook 数据库上完成 25 项离线自动化测试。测试覆盖 Schema、表选择、JOIN 补全、校验、改写、执行、空结果、禁止写操作和端到端调用。

详见 [设计说明](docs/设计说明.md) 与 [测试与验收报告](docs/测试与验收报告.md)。

## 7. 学习与复盘入口

阅读顺序：`models.py → db/catalog.py → agents/ → db/validator.py → db/executor.py → workflow.py → tests/`。

关键知识点：Pydantic 结构化输出、SQLite 外键图、BFS、Agent 编排、SQL 检查、自动修复闭环与数据结果可信性。
