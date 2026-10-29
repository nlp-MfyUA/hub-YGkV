# SQL Agent 工作流 Demo · LangChain 架构版（Python · 前后端分离）

一个**固定流程**的 SQL Agent 工作流演示项目：输入自然语言问题，依次经过
**数据库解析 → Table 选择 → SQL 生成 → SQL 校验 → SQL 改写 → SQL 执行 → 结果汇总**
七个阶段产出答案；校验或执行失败时携带错误信息进入「SQL 改写」重试，有次数上限与兜底。

- 数据库：SQLite 内置电商示例库（用户 / 商品 / 订单 / 订单明细，确定性种子数据）
- LLM：DeepSeek（OpenAI 兼容协议，经 `langchain-openai` 的 `ChatOpenAI` 调用），
  也内置离线 `MockChatModel`（自定义 `BaseChatModel`），无 Key 也能跑通全链路
- 评测：15 条覆盖三种难度的测试问题，双指标（执行成功率 + 结果正确率）+ Markdown 报告
- 架构：**前后端分离** —— FastAPI 后端（REST API）+ Streamlit 前端（纯 HTTP 客户端）

> 本版是 [week11/sql-agent-demo](../week11/sql-agent-demo) 的 **LangChain 框架重构版**：
> 工作流阶段、留痕、评测指标、API/CLI 行为与 week11 完全一致，但核心工作流从
> 「裸调 OpenAI SDK + 手写编排」迁移到 LangChain 技术栈，见下文「架构对比」。

## 架构图

```
┌────────────────────────────┐         HTTP / JSON          ┌─────────────────────────────────┐
│  Streamlit 前端（纯客户端）  │  ────────────────────────►  │  FastAPI 后端（uvicorn :8000）   │
│  frontend/                 │   POST /api/query            │  backend/                       │
│  ├─ 单条查询（流程可视化）   │   ◄────────────────────────   │  ├─ routers/   health/query/     │
│  ├─ 批量评测（指标+报告）    │   traces / SQL / 结果 / 总结  │  │             schema/eval       │
│  └─ 数据库结构浏览          │   POST /api/eval             │  └─ service.py ──► SqlAgentWorkflow
└────────────────────────────┘   GET  /api/schema           │         └─ sql_agent/（7 stages） │
            ▲                    GET  /api/health           │         └─ eval/（测试集+指标）   │
            └── 不 import 任何核心包，只发 HTTP 请求           └─────────────────────────────────┘
                                                                            │
                                                                    SQLite（只读执行 + authorizer）
```

## 与 week11 的架构对比（迁移对照）

week11 的核心工作流是「裸调 SDK + 手写编排」；week12 把它按 LangChain 的分层习惯重组，
**阶段划分与外部行为不变**，每层替换如下：

| 关注点 | week11（手写） | week12（LangChain 架构） |
| --- | --- | --- |
| 模型调用 | `openai.OpenAI` 自建 `DeepSeekClient` | `langchain_openai.ChatOpenAI`（DeepSeek 走 OpenAI 兼容协议） |
| 离线模拟 | 自建 `MockClient`（另一套接口） | `MockChatModel(BaseChatModel)`，与真实模型同接口、同链 |
| Prompt | 手拼 `messages` 字典 + f-string | `ChatPromptTemplate`（system/human 与变量分离） |
| 输出解析 | 各 stage 内联 `extract_sql` / `extract_json` | LCEL 链末端 parser（`RunnableLambda`），携带 usage |
| 阶段组合 | stage 各自 `llm.chat(...)` | LCEL 链：`prompt \| model \| parser`（`sql_agent/chains.py`） |
| 流程编排 | `workflow.py` 手写 for 循环 + break/continue | `langgraph` 的 `StateGraph`：七节点 + 条件边重试回路（`sql_agent/graph.py`） |
| Token 统计 | 自建 `LLMResponse.usage` 累加 | `AIMessage.usage_metadata` → `LLMUsage` 映射 |

LangChain 四层在代码中的落点：

```
sql_agent/
├── llm.py      # ① ChatModel 层：ChatOpenAI / MockChatModel（都实现 BaseChatModel）
├── prompts.py  # ② Prompt 层：四个 ChatPromptTemplate + 输出解析工具
├── chains.py   # ③ Chain 层（LCEL）：prompt | model | parser，共四条链
├── graph.py    # ④ 编排层（LangGraph）：WorkflowState + StateGraph
└── workflow.py #   组装：建链 → 建七个 stage → 编译状态图 → run/invoke
```

## 快速开始

本项目基于 **Python 3.12**（本机使用 conda 环境 `py312`，Python 3.12.13）。
以下命令均假设已激活该环境；如使用其他环境，需自行安装 `requirements.txt` 中的依赖
（`langchain` / `langchain-openai` / `langgraph` / `sqlglot` / `fastapi` / `uvicorn` /
`streamlit` / `requests` / `pandas`）。

```bash
# 0. 激活环境（conda）
conda activate py312

# 1. 安装依赖（py312 已预装 langchain 1.3 / langgraph 1.2 / langchain-openai 1.1 等）
pip install -r requirements.txt

# 2. 配置 API Key
#    首次运行会自动从 config.example.yaml 复制生成 config.local.yaml，
#    编辑它把 llm.api_key 换成你的 DeepSeek Key（也可用环境变量 LLM_API_KEY）

# 3. 启动后端（终端 1，在项目根目录执行）
uvicorn backend.app:app --port 8000
#    mock 模式（无需 Key）：LLM_PROVIDER=mock uvicorn backend.app:app --port 8000
#    交互式 API 文档：http://127.0.0.1:8000/docs

# 4. 启动前端（终端 2）
streamlit run frontend/app.py
#    浏览器打开 http://localhost:8501
```

> 本机 conda `py312` 环境已安装：Python 3.12.13 / langchain 1.3.14 /
> langchain-core 1.5.2 / langchain-openai 1.1.9 / langgraph 1.2.10 /
> fastapi 0.141 / uvicorn 0.40 / streamlit 1.61 / pandas 3.0 /
> PyYAML / requests / sqlglot 30.24。

## 一键启动脚本（scripts/）

`scripts/` 下提供了 Windows 批处理（`.bat`）与 Git Bash（`.sh`）两套脚本，
自动完成「激活 conda py312 → 切换项目目录 → 启动服务」，无需手动敲命令。

| 脚本 | 作用 |
| --- | --- |
| `start_backend.bat` / `start_backend.sh` | 启动后端（FastAPI，默认 8000 端口） |
| `start_frontend.bat` / `start_frontend.sh` | 启动前端（Streamlit，默认 8501 端口） |
| `start_all.bat` / `start_all.sh` | 一键同时启动前后端 |

```bat
REM ============ Windows（CMD / 资源管理器双击）============
scripts\start_all.bat --mock          REM 一键启动（mock 离线模式，无需 Key）
scripts\start_backend.bat             REM 仅后端（DeepSeek 模式，需 Key）
scripts\start_backend.bat --mock      REM 仅后端（mock 模式）
scripts\start_frontend.bat            REM 仅前端
```

```bash
# ============ Git Bash ============
./scripts/start_all.sh --mock         # 一键启动（Ctrl+C 同时停止两个服务）
./scripts/start_backend.sh --mock     # 仅后端
./scripts/start_frontend.sh           # 仅前端
```

通用参数：`--mock` 启用离线 mock 模式（无需 API Key）；`--port N` 覆盖默认端口
（`start_all.sh` 另支持环境变量 `BACKEND_PORT` / `FRONTEND_PORT`）。

Windows 下的 `start_all.bat` 会在两个独立控制台窗口分别启动服务，关闭窗口即停止；
Git Bash 下的 `start_all.sh` 在单终端运行，Ctrl+C 一起停止，并会等待后端就绪后再拉起前端。

前端页面：

- **💬 单条查询**：输入问题 → 运行工作流 → 流程总览（七个阶段的 🟢/🔴 状态线）+
  各阶段明细（输入/输出/校验项/耗时/token）+ 最终 SQL + 执行结果表 + LLM 总结；
- **📊 批量评测**：一键跑 15 条测试问题，展示执行成功率 / 结果正确率等指标卡、
  汇总表，并支持下载 Markdown 报告；
- **🗄️ 数据库结构**：按需从后端加载实时 schema（表/列/类型/注释/枚举取值/外键/DDL）。

侧边栏可修改后端地址、重试上限、是否执行结果汇总，并可一键检查连接。

## 工作流图（LangGraph 状态机）

```
START ─► db_parser ─► table_selector ─┬─(未选到表)──────────────► END(失败)
                                       └─► sql_generate ─┬─(无SQL)─┐
                                                          │         ▼
                                                (有SQL)─►│   sql_validate ─┬─(未通过)─► rewrite_router
                                                          │                 │
                                                          │         (通过)─►│ sql_execute ─┬─(报错)─► rewrite_router
                                                          │                 │              │
                                                          │                 │      (成功)─►│ summarize ─► END(成功)
                                                          ▼                 ▼              ▼
                                                rewrite_router ◄──────────────────────────┘
                                                  ├─(LLM 不可用 / 次数耗尽)──► END(失败)
                                                  └─► sql_rewrite ─► sql_validate（回边）
```

对应约定（与 week11 一致）：

- 第 1 次尝试走「SQL 生成」，第 2 次起走「SQL 改写」（`attempt` 由节点推进）；
- 任一阶段产生 LLM 调用都会记录 token 用量（`AIMessage.usage_metadata`）；
- 重试耗尽后返回 `success=False` 与兜底说明，不抛异常。

## 七个 Stage

| # | Stage | 职责 | 关键实现 |
| --- | --- | --- | --- |
| 1 | 数据库解析 | 连接库并抽取完整 schema | `PRAGMA table_info/foreign_key_list` + `sqlite_master`；抽取行数、低基数列取值（如订单状态枚举）、样例行，渲染为 LLM 可读的表结构说明 |
| 2 | Table 选择 | 筛选候选表，收窄生成上下文 | LCEL 链 `SELECT_TABLES_PROMPT \| model \| parse_tables_output`（结构化 JSON）；失败时退化到关键词/别名启发式；无命中兜底全表 |
| 3 | SQL 生成 | 问题 + 候选表 schema → SQL | LCEL 链 `GENERATE_SQL_PROMPT \| model \| parse_sql_output`；Prompt 含 DDL、列注释、枚举取值、样例行；输出 ` ```sql ` 代码块 |
| 4 | SQL 校验 | 六道检查，不调用 LLM | sqlglot 语法解析 → 单语句 → 仅 SELECT（AST 禁写操作/DDL/PRAGMA）→ 表白名单 → 列白名单（解析表别名/CTE/别名列）→ 只读连接 EXPLAIN 语义预检 |
| 5 | SQL 改写 | 携带错误信息修复 SQL | 仅失败后触发（LangGraph 回边）；LCEL 链 `REWRITE_SQL_PROMPT \| model \| parse_sql_output`；Prompt 含原 SQL + 具体错误 |
| 6 | SQL 执行 | 安全地执行查询 | 只读连接（`mode=ro`）+ authorizer 只放行读取/函数（拒绝 `load_extension`）+ 行数上限 + 软超时 |
| 7 | 结果汇总 | 结果 → 自然语言结论 | LCEL 链 `SUMMARIZE_PROMPT \| model.bind(temperature=0.3) \| parse_text_output`；空结果明确说明「没有符合条件的数据」 |

## API 一览

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/query` | 运行一次工作流。请求 `{"question": "...", "max_attempts": 3, "summarize": true}`；返回七阶段留痕、最终 SQL、执行结果、LLM 总结、token 用量 |
| `GET /api/schema` | 结构化数据库 schema（表/列/类型/注释/枚举/外键/DDL） |
| `POST /api/eval` | 批量评测。请求 `{"ids": "1,5,8"}`（可省略）；返回指标、逐题明细、Markdown 报告全文，并写入 `reports/` |
| `GET /api/health` | 服务状态、当前模型、数据库路径、表数量 |

错误约定：`503` = LLM 不可用（未配置 Key 等，附明确指引）；`400` = 参数非法（如 ids 无匹配）；
工作流自身失败不抛 5xx，而是在 `200` 响应里以 `success=false` + 各阶段留痕返回。

## CLI（开发调试用，与 API 等价）

```bash
conda activate py312   # 或任意已装依赖的 Python 3.12 环境
python main.py ask "每个城市有多少用户？"   # 单条，逐 stage 打印
python main.py eval                        # 批量评测 + 报告
python main.py init-db                     # 重建示例数据库
python main.py --provider mock eval        # 离线 mock 模式
```

## Mock 模式说明

`provider: mock`（或 `--provider mock` / `LLM_PROVIDER=mock`）使用内置
`MockChatModel`：一个实现了 LangChain `BaseChatModel` 接口的离线模型，按
system prompt 特征词分派，用固定规则模拟各阶段输出——**它与真实
`ChatOpenAI` 走完全相同的 LCEL 链**（`prompt | model | parser`），切换模型
只需要改配置，这正是 LangChain 模型抽象的价值。

mock 模式下 **Q8 会被故意生成错误的列名（`orders.amount`）**，用于完整演示
「SQL 校验拦截 → SQL 改写 → 重试通过」回路——mock 评测报告中 Q8 尝试次数为 2。
CLI 与后端 API 的 mock 行为完全一致（共享 `eval.test_queries.register_mock_knowledge_from_tests`）。

## 开发辅助工具（dev/）

| 脚本 | 用途 |
| --- | --- |
| `dev/mock_openai_server.py` | 本地 OpenAI 兼容模拟服务器，验证 `ChatOpenAI` 的 SDK 接线（请求/响应/401）而不消耗真实额度 |
| `dev/test_frontend.py` | 基于 Streamlit AppTest 的**无浏览器前端全流程验证**：渲染 → 连接检查 → 运行工作流 → 加载 schema。运行前需先启动 mock 后端 |

```bash
# 前端自动化验证（需后端已在 mock 模式运行）
LLM_PROVIDER=mock uvicorn backend.app:app --port 8000 &
python dev/test_frontend.py
```

## 配置项（config.local.yaml）

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `llm.provider` | `deepseek` | `deepseek` 真实 API（ChatOpenAI）/ `mock` 离线模拟 |
| `llm.base_url` | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `llm.api_key` | 空 | DeepSeek Key（环境变量 `LLM_API_KEY` 优先） |
| `llm.model` | `deepseek-chat` | 模型名 |
| `llm.net_max_retries` | `2` | 网络层重试（底层 openai SDK，限流/超时/5xx 才重试） |
| `eval.max_attempts` | `3` | 工作流重试上限（生成 + 改写总次数） |
| `eval.row_limit` | `100` | 执行阶段最多返回行数 |
| `eval.query_timeout_seconds` | `10` | 单条 SQL 执行超时 |
| `eval.summarize` | `true` | 是否调用 LLM 做结果汇总 |

环境变量覆盖：`LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`。
后端还支持 `SQL_AGENT_CONFIG` 指定配置文件路径。

## 评测指标

- **执行成功率**：工作流在重试预算内产出并成功执行 SQL 的比例；
- **结果正确率**：执行结果与 gold SQL 结果一致的比例——
  `严格一致`（列序敏感）或 `宽松一致`（忽略行内列顺序，容忍模型调整输出列序）都算正确；
  数值按 2 位小数归一化，`int 3` 与 `float 3.0` 视为相等；
- 另统计平均尝试次数、平均耗时、token 用量、触发改写重试的条数、各 stage 错误次数。

CLI 在控制台打印汇总表；API 模式下返回 JSON 指标 + Markdown 报告全文（前端可下载），
后端同时写入 `reports/eval_report_<时间戳>.md`。

## 目录结构

```
sql-agent-demo/
├── main.py                     # CLI 入口：ask / eval / init-db（开发调试用）
├── config.example.yaml         # 配置模板
├── config.local.yaml           # 本地配置（含 Key，已被 .gitignore 忽略）
├── requirements.txt            # 全部依赖（LangChain 核心 + 后端 + 前端）
├── README.md
├── backend/                    # ── 后端（FastAPI）
│   ├── app.py                  #   应用工厂 + CORS + 路由注册（uvicorn 入口）
│   ├── service.py              #   服务层：单例工作流 + query/schema/eval
│   ├── schemas.py              #   Pydantic 请求模型
│   ├── deps.py                 #   服务单例依赖注入
│   └── routers/                #   health / query / schema / eval 四个路由
├── frontend/                   # ── 前端（Streamlit，纯 HTTP 客户端）
│   ├── app.py                  #   页面入口：侧边栏 + 三个标签页
│   ├── api_client.py           #   后端 API 客户端（requests）
│   └── components.py           #   UI 组件：流程时间线 / 结果表 / 评测报告
├── sql_agent/                  # ── 共享核心（仅后端使用，LangChain 架构）
│   ├── config.py               #   配置加载 + 环境变量覆盖
│   ├── db.py                   #   示例库建库/种子数据 + schema 解析 + 只读连接
│   ├── llm.py                  #   ChatModel 层：ChatOpenAI + MockChatModel(BaseChatModel)
│   ├── models.py               #   StageTrace / WorkflowResult 等数据模型
│   ├── prompts.py              #   ChatPromptTemplate 模板 + 输出解析工具
│   ├── chains.py               #   LCEL 链：prompt | model | parser（四条）
│   ├── graph.py                #   LangGraph 状态机：七节点 + 改写重试回路
│   ├── workflow.py             #   组装各 stage + 编译/驱动状态图
│   └── stages/                 #   七个 stage，一个模块一个
│       ├── db_parser.py        #     1 数据库解析
│       ├── table_selector.py   #     2 Table 选择（LCEL 链）
│       ├── sql_generator.py    #     3 SQL 生成（LCEL 链）
│       ├── sql_validator.py    #     4 SQL 校验
│       ├── sql_rewriter.py     #     5 SQL 改写（LCEL 链）
│       ├── sql_executor.py     #     6 SQL 执行
│       └── summarizer.py       #     7 结果汇总（LCEL 链）
├── eval/                       # ── 评测（后端 /api/eval 与 CLI 共用）
│   ├── test_queries.py         #   15 条测试问题 + gold SQL + mock 知识注册
│   ├── runner.py               #   批量执行 + 指标计算 + 结果比对
│   └── report.py               #   控制台摘要 + Markdown 报告
├── dev/
│   ├── mock_openai_server.py   #   本地 OpenAI 兼容模拟服务器（验证 SDK 接线）
│   └── test_frontend.py        #   Streamlit AppTest 无浏览器全流程验证
├── scripts/                    # ── 一键启动脚本（.bat Windows / .sh Git Bash）
│   ├── start_backend.bat       #   启动后端（--mock / --port）
│   ├── start_frontend.bat      #   启动前端（--port）
│   ├── start_all.bat           #   一键双启（两个独立窗口）
│   ├── start_backend.sh        #   启动后端（--mock / --port）
│   ├── start_frontend.sh       #   启动前端（--port）
│   └── start_all.sh            #   一键双启（单终端，Ctrl+C 同停）
├── data/                       # 示例数据库（自动生成）
└── reports/                    # 评测报告输出
```

## 常见问题

- **后端启动时报 `FileNotFoundError` / SSL 相关错误**：conda 激活可能把 `SSL_CERT_FILE`
  指向不存在的路径（本机 `py312` 即如此：激活脚本指向 `<env>/ssl/cacert.pem`，
  实际 cacert 在 `<env>/Library/ssl/` 下），导致 ChatOpenAI 底层 httpx 创建客户端时崩溃。
  `scripts/` 下的启动脚本已内置自愈（自动重定向到真实 cacert 或清除该变量）；
  手动启动时可执行 `unset SSL_CERT_FILE`（Bash）或确认该路径存在。
- **前端提示「无法连接后端」**：先确认后端已启动（`uvicorn backend.app:app --port 8000`），
  再检查侧边栏的后端地址；`/api/health` 可以直接用浏览器访问验证。
- **/api/health 显示 error 或 query 返回 503**：未配置 API Key。编辑 `config.local.yaml`
  的 `llm.api_key`，或用 `LLM_PROVIDER=mock` 启动后端离线运行。
- **401 / AuthenticationError**：Key 错误，工作流会立即中止并给出明确错误（不会浪费重试）。
- **连接超时**：检查网络能否访问 `api.deepseek.com`，或调大 `llm.timeout_seconds`。
- **想改测试问题**：编辑 `eval/test_queries.py`，`gold_sql` 按 `data/ecommerce.db` 的数据编写。
- **换数据库**：修改 `db.path` 指向你的 SQLite 文件即可；schema 解析逻辑通用
  （MySQL/PostgreSQL 需替换驱动与 `PRAGMA` 部分，可作为练习）。
- **结果判为「不一致」但数据看起来对**：检查是否为浮点尾差（已按 2 位归一化）或
  输出列顺序差异（宽松匹配已覆盖）；报告中有 gold 与实际行数对比可定位。

## 设计取舍说明

1. **为什么没有直接用 `create_sql_query_chain` 等 LangChain 现成 SQL 链？**
   本项目的教学重点是「固定流程的可见性与可控性」——七个阶段逐一留痕、
   六道校验、改写重试回路、双指标评测，都是现成 SQL 链不暴露的内部细节。
   因此只把 LangChain 的分层（ChatModel / Prompt / LCEL / LangGraph）用足，
   流程本身仍按固定阶段显式编排；schema 解析也保留自研实现（LangChain 的
   `SQLDatabase` 不带列注释 / 低基数枚举 / 行数等本项目依赖的信息）。
2. **为什么 mock 也做成 `BaseChatModel`？** 让离线模拟与真实模型同接口、同链，
   `prompt | model | parser` 对两种模型完全一致，切换零成本；顺带演示了
   LangChain 模型抽象的扩展点。
3. **状态机为什么用 LangGraph 而不是 LCEL 循环？** 本工作流有环
   （校验/执行失败 → 改写 → 重试），LangGraph 的 `StateGraph` + 条件边
   能声明式表达节点与回边，state（含 traces 累加 reducer）即工作流上下文，
   比手写循环更直观，也是 LangChain 生态中带环流程的标准做法。
