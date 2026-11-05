# SQL Agent 工作流 Demo · LangGraph 框架版（Python · 前后端分离）

一个**固定流程**的 SQL Agent 工作流演示项目：输入自然语言问题，依次经过
**数据库解析 → Table 选择 → SQL 生成 → SQL 校验 → SQL 改写 → SQL 执行 → 结果汇总**
七个阶段产出答案；校验或执行失败时携带错误信息进入「SQL 改写」重试，有次数上限与兜底。

- 数据库：SQLite 内置电商示例库（用户 / 商品 / 订单 / 订单明细，确定性种子数据）
- LLM：DeepSeek（OpenAI 兼容协议，经 `langchain-openai` 的 `ChatOpenAI` 调用），
  也内置离线 `MockChatModel`（自定义 `BaseChatModel`），无 Key 也能跑通全链路
- 评测：15 条覆盖三种难度的测试问题，双指标（执行成功率 + 结果正确率）+ Markdown 报告
- 架构：**前后端分离** —— FastAPI 后端（REST API + SSE 流式）+ Streamlit 前端（纯 HTTP 客户端）

> 本版是 [week12/sql-agent-demo](../week12/sql-agent-demo) 的 **LangGraph 框架重构版**：
> 阶段划分、留痕、评测指标、API/CLI 行为与 week12 完全一致，但核心工作流从
> 「LangChain 分层（LCEL 链 + StateGraph）」收敛为「LangGraph 一体」——
> 图带 checkpointer 编译、节点内直调模型、逐节点流式驱动、状态可回查、图可导出。

## 架构图

```
┌────────────────────────────┐         HTTP / JSON          ┌─────────────────────────────────┐
│  Streamlit 前端（纯客户端）  │  ────────────────────────►  │  FastAPI 后端（uvicorn :8000）   │
│  frontend/                 │   POST /api/query            │  backend/                       │
│  ├─ 单条查询（SSE 流式进度） │   POST /api/query/stream(SSE)│  ├─ routers/   health/query/     │
│  ├─ 批量评测（指标+报告）    │   GET  /api/schema           │  │             schema/eval/      │
│  ├─ 数据库结构浏览          │   GET  /api/graph            │  │             graph/state       │
│  └─ 工作流图 + 状态回查      │   GET  /api/state/{id}       │  └─ service.py ──► SqlAgentWorkflow
└────────────────────────────┘   GET  /api/health           │         └─ sql_agent/（LangGraph）│
            ▲                    ◄────────────────────────   │         └─ eval/（测试集+指标）   │
            └── 不 import 任何核心包，只发 HTTP 请求           └─────────────────────────────────┘
                                                                            │
                                                              LangGraph 状态机 + checkpointer
                                                                            │
                                                                    SQLite（只读执行 + authorizer）
```

## 与 week11 / week12 的架构对比（迁移对照）

week11 是「裸调 SDK + 手写编排」；week12 引入 LangChain 分层（LCEL 链 + StateGraph）；
week13 把编排完全交给 LangGraph，LangChain 只保留模型抽象与提示词模板：

| 关注点 | week11（手写） | week12（LangChain 架构） | week13（LangGraph 框架） |
| --- | --- | --- | --- |
| 模型调用 | `openai.OpenAI` 自建 `DeepSeekClient` | `langchain_openai.ChatOpenAI` | 同 week12（`ChatOpenAI` / `MockChatModel`） |
| Prompt | 手拼 `messages` 字典 + f-string | `ChatPromptTemplate` | 同 week12 |
| 输出解析 | 各 stage 内联 `extract_sql` / `extract_json` | LCEL 链末端 parser（`RunnableLambda`） | 节点内 `call_llm(..., parser=...)`（`llm_call.py`） |
| 阶段组合 | stage 各自 `llm.chat(...)` | LCEL 链：`prompt \| model \| parser`（`chains.py`） | **取消链层**，节点内直调模型 |
| 流程编排 | `workflow.py` 手写 for 循环 | `StateGraph`：七节点 + 条件边重试回路 | 同 week12，且**图带 checkpointer 编译** |
| 状态 | 局部变量 | LangGraph state（traces 累加 reducer） | 同 week12，且**每次运行 = 一个 thread_id，可回查/回放** |
| 执行方式 | `run()` 一把跑完 | `graph.invoke()` | `invoke()` + **`stream()` 逐节点流式** |
| 可观测性 | 控制台打印 | 七阶段留痕 | 同 week12，且 **SSE 实时推送 + Mermaid 图导出** |

week13 的代码落点：

```
sql_agent/
├── llm.py       # ① ChatModel 层：ChatOpenAI / MockChatModel（都实现 BaseChatModel）
├── prompts.py   # ② Prompt 层：四个 ChatPromptTemplate + 输出解析工具
├── llm_call.py  # ③ 节点内 LLM 直调：format -> invoke -> parse（取代 week12 的 chains.py）
├── checkpoint.py# ④ checkpointer 工厂：MemorySaver / SqliteSaver（含序列化白名单）
├── graph.py     # ⑤ 编排层（LangGraph）：WorkflowState + StateGraph + 流式序列化
└── workflow.py  #   组装：建 stage → 编译状态图 → run / stream / get_state / mermaid
```

## week13 新增的 LangGraph 能力

1. **checkpointer 持久化**：状态机编译时挂上 checkpointer（`memory` 进程内 /
   `sqlite` 落库，见配置），每个节点执行后自动落一个状态快照。
2. **thread_id 线程语义**：每次运行分配独立 `thread_id`，响应里带回；
   `GET /api/state/{thread_id}` 可回查该次运行的完整状态（SQL / 留痕 / 结果）。
3. **逐节点流式（SSE）**：`POST /api/query/stream` 基于
   `graph.stream(stream_mode="updates")` 实时推送 `start / node / result / error`
   事件，前端「单条查询」页可一边跑一边看每个节点的产出（含改写重试回路）。
4. **图即代码**：`GET /api/graph`（或 CLI `python main.py graph`）导出状态机的
   Mermaid 图，八个节点与改写回边一目了然。

## 快速开始

本项目基于 **Python 3.12**（本机使用 conda 环境 `py312`，Python 3.12.13）。
以下命令均假设已激活该环境；如使用其他环境，需自行安装 `requirements.txt` 中的依赖
（`langgraph` / `langgraph-checkpoint` / `langchain-core` / `langchain-openai` /
`sqlglot` / `fastapi` / `uvicorn` / `streamlit` / `requests` / `pandas`）。

```bash
# 0. 激活环境（conda）
conda activate py312

# 1. 安装依赖（py312 已预装 langgraph 1.2 / langchain-core 1.5 /
#    langchain-openai 1.1 / fastapi 0.141 / streamlit 1.61 等）
pip install -r requirements.txt
#    如需 sqlite checkpoint（graph.checkpoint: sqlite），额外安装：
#    pip install langgraph-checkpoint-sqlite

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

> 本机 conda `py312` 环境已安装：Python 3.12.13 / langgraph 1.2.10 /
> langgraph-checkpoint 4.1.1 / langchain-core 1.5.2 / langchain-openai 1.1.9 /
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

- **💬 单条查询**：输入问题 → 运行工作流（默认 SSE 流式，实时展示 LangGraph
  逐节点进度，可开关）→ 流程总览（七个阶段的 🟢/🔴 状态线）+
  各阶段明细（输入/输出/校验项/耗时/token）+ 最终 SQL + 执行结果表 + LLM 总结；
- **📊 批量评测**：一键跑 15 条测试问题，展示执行成功率 / 结果正确率等指标卡、
  汇总表，并支持下载 Markdown 报告；
- **🗄️ 数据库结构**：按需从后端加载实时 schema（表/列/类型/注释/枚举取值/外键/DDL）；
- **🧭 工作流图**（week13 新增）：状态机 Mermaid 图 + thread_id 状态回查。

侧边栏可修改后端地址、重试上限、是否执行结果汇总、是否流式运行，
并可一键检查连接、回查最近一次运行的线程状态。

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

对应约定（与 week11 / week12 一致）：

- 第 1 次尝试走「SQL 生成」，第 2 次起走「SQL 改写」（`attempt` 由节点推进）；
- 任一阶段产生 LLM 调用都会记录 token 用量（`AIMessage.usage_metadata`）；
- 重试耗尽后返回 `success=False` 与兜底说明，不抛异常。

## 七个 Stage

| # | Stage | 职责 | 关键实现 |
| --- | --- | --- | --- |
| 1 | 数据库解析 | 连接库并抽取完整 schema | `PRAGMA table_info/foreign_key_list` + `sqlite_master`；抽取行数、低基数列取值（如订单状态枚举）、样例行，渲染为 LLM 可读的表结构说明 |
| 2 | Table 选择 | 筛选候选表，收窄生成上下文 | 节点内 `call_llm(model, SELECT_TABLES_PROMPT, ..., parser=json)`（结构化 JSON）；失败时退化到关键词/别名启发式；无命中兜底全表 |
| 3 | SQL 生成 | 问题 + 候选表 schema → SQL | 节点内 `call_llm(..., parser=sql)`；Prompt 含 DDL、列注释、枚举取值、样例行；输出 ` ```sql ` 代码块 |
| 4 | SQL 校验 | 六道检查，不调用 LLM | sqlglot 语法解析 → 单语句 → 仅 SELECT（AST 禁写操作/DDL/PRAGMA）→ 表白名单 → 列白名单（解析表别名/CTE/别名列）→ 只读连接 EXPLAIN 语义预检 |
| 5 | SQL 改写 | 携带错误信息修复 SQL | 仅失败后触发（LangGraph 回边）；节点内 `call_llm(..., parser=sql)`；Prompt 含原 SQL + 具体错误 |
| 6 | SQL 执行 | 安全地执行查询 | 只读连接（`mode=ro`）+ authorizer 只放行读取/函数（拒绝 `load_extension`）+ 行数上限 + 软超时 |
| 7 | 结果汇总 | 结果 → 自然语言结论 | 节点内 `call_llm(..., parser=text, temperature=0.3)`；空结果明确说明「没有符合条件的数据」 |

## API 一览

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/query` | 运行一次工作流。请求 `{"question": "...", "max_attempts": 3, "summarize": true, "thread_id": "可选"}`；返回七阶段留痕、最终 SQL、执行结果、LLM 总结、token 用量、thread_id |
| `POST /api/query/stream` | 流式版（SSE）。事件 `start` / `node` / `result` / `error`；最终 `result` 载荷与 `/api/query` 响应一致 |
| `GET /api/schema` | 结构化数据库 schema（表/列/类型/注释/枚举/外键/DDL） |
| `POST /api/eval` | 批量评测。请求 `{"ids": "1,5,8"}`（可省略）；返回指标、逐题明细、Markdown 报告全文，并写入 `reports/` |
| `GET /api/graph` | 状态机 Mermaid 图（week13 新增） |
| `GET /api/state/{thread_id}` | 回查某次运行的状态快照（week13 新增，404 = 线程不存在） |
| `GET /api/health` | 服务状态、当前模型、数据库路径、表数量 |

错误约定：`503` = LLM 不可用（未配置 Key 等，附明确指引）；`400` = 参数非法（如 ids 无匹配）；
`404` = thread_id 不存在；工作流自身失败不抛 5xx，而是在 `200` 响应里以 `success=false`
+ 各阶段留痕返回。

## CLI（开发调试用，与 API 等价）

```bash
conda activate py312   # 或任意已装依赖的 Python 3.12 环境
python main.py ask "每个城市有多少用户？"   # 单条，逐 stage 打印
python main.py eval                        # 批量评测 + 报告
python main.py init-db                     # 重建示例数据库
python main.py graph                       # 导出 LangGraph 状态机 Mermaid 图
python main.py --provider mock eval        # 离线 mock 模式
```

## Mock 模式说明

`provider: mock`（或 `--provider mock` / `LLM_PROVIDER=mock`）使用内置
`MockChatModel`：一个实现了 LangChain `BaseChatModel` 接口的离线模型，按
system prompt 特征词分派，用固定规则模拟各阶段输出——**它与真实
`ChatOpenAI` 走完全相同的节点内直调逻辑**（`call_llm`），切换模型
只需要改配置，这正是 LangChain 模型抽象的价值。

mock 模式下 **Q8 会被故意生成错误的列名（`orders.amount`）**，用于完整演示
「SQL 校验拦截 → SQL 改写 → 重试通过」回路——mock 评测报告中 Q8 尝试次数为 2。
CLI 与后端 API 的 mock 行为完全一致（共享 `eval.test_queries.register_mock_knowledge_from_tests`）。

## 开发辅助工具（dev/）

| 脚本 | 用途 |
| --- | --- |
| `dev/mock_openai_server.py` | 本地 OpenAI 兼容模拟服务器，验证 `ChatOpenAI` 的 SDK 接线（请求/响应/401）而不消耗真实额度 |
| `dev/test_frontend.py` | 基于 Streamlit AppTest 的**无浏览器前端全流程验证**：渲染 → 连接检查 → 运行工作流（SSE 流式，含重试回路）→ 加载 schema → 验证 `/api/graph` 与 `/api/state`。运行前需先启动 mock 后端 |

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
| `graph.checkpoint` | `memory` | LangGraph checkpoint 后端：`memory`（进程内）/ `sqlite`（落库，需 `langgraph-checkpoint-sqlite`） |
| `graph.checkpoint_path` | `data/checkpoints.sqlite` | sqlite 模式下的 checkpoint 库路径 |

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
├── main.py                     # CLI 入口：ask / eval / init-db / graph
├── config.example.yaml         # 配置模板（含 graph 段）
├── config.local.yaml           # 本地配置（含 Key，已被 .gitignore 忽略）
├── requirements.txt            # 全部依赖（LangGraph 核心 + 后端 + 前端）
├── README.md
├── backend/                    # ── 后端（FastAPI）
│   ├── app.py                  #   应用工厂 + CORS + 路由注册（uvicorn 入口）
│   ├── service.py              #   服务层：单例工作流 + query/stream/schema/eval/graph/state
│   ├── schemas.py              #   Pydantic 请求模型（含 thread_id）
│   ├── deps.py                 #   服务单例依赖注入
│   └── routers/                #   health / query(含SSE) / schema / eval / graph / state
├── frontend/                   # ── 前端（Streamlit，纯 HTTP 客户端）
│   ├── app.py                  #   页面入口：侧边栏 + 四个标签页
│   ├── api_client.py           #   后端 API 客户端（requests，含 SSE 解析）
│   └── components.py           #   UI 组件：流式进度 / 流程时间线 / 结果表 / 评测报告 / 状态机图
├── sql_agent/                  # ── 共享核心（仅后端使用，LangGraph 框架）
│   ├── config.py               #   配置加载 + 环境变量覆盖 + graph 段
│   ├── db.py                   #   示例库建库/种子数据 + schema 解析 + 只读连接
│   ├── llm.py                  #   ChatModel 层：ChatOpenAI + MockChatModel(BaseChatModel)
│   ├── llm_call.py             #   节点内 LLM 直调（format -> invoke -> parse）
│   ├── checkpoint.py           #   checkpointer 工厂（MemorySaver / SqliteSaver + 序列化白名单）
│   ├── models.py               #   StageTrace / WorkflowResult 等数据模型
│   ├── prompts.py              #   ChatPromptTemplate 模板 + 输出解析工具
│   ├── graph.py                #   LangGraph 状态机：七节点 + 改写重试回路 + 流式序列化
│   ├── workflow.py             #   组装与驱动：run / stream / get_state / mermaid
│   └── stages/                 #   七个 stage，一个模块一个
│       ├── db_parser.py        #     1 数据库解析
│       ├── table_selector.py   #     2 Table 选择（LLM 直调）
│       ├── sql_generator.py    #     3 SQL 生成（LLM 直调）
│       ├── sql_validator.py    #     4 SQL 校验
│       ├── sql_rewriter.py     #     5 SQL 改写（LLM 直调）
│       ├── sql_executor.py     #     6 SQL 执行
│       └── summarizer.py       #     7 结果汇总（LLM 直调）
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
├── data/                       # 示例数据库（自动生成）+ checkpoints.sqlite（sqlite 模式）
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
- **流式页面一直转圈**：确认后端版本支持 `/api/query/stream`（week13 起）；
  流式失败时前端会自动回退到普通模式并提示。
- **`/api/state` 返回 404**：线程不存在——进程重启后 memory checkpoint 即失效，
  需要跨重启回查请把 `graph.checkpoint` 改成 `sqlite`。
- **401 / AuthenticationError**：Key 错误，工作流会立即中止并给出明确错误（不会浪费重试）。
- **连接超时**：检查网络能否访问 `api.deepseek.com`，或调大 `llm.timeout_seconds`。
- **想改测试问题**：编辑 `eval/test_queries.py`，`gold_sql` 按 `data/ecommerce.db` 的数据编写。
- **换数据库**：修改 `db.path` 指向你的 SQLite 文件即可；schema 解析逻辑通用
  （MySQL/PostgreSQL 需替换驱动与 `PRAGMA` 部分，可作为练习）。
- **结果判为「不一致」但数据看起来对**：检查是否为浮点尾差（已按 2 位归一化）或
  输出列顺序差异（宽松匹配已覆盖）；报告中有 gold 与实际行数对比可定位。

## 设计取舍说明

1. **为什么 week13 取消 LCEL 链层？** week12 的链层（`chains.py`）解决的是
   「prompt/model/parser 复用」问题，但它把调用点从业务节点里抽走，节点反而要通过
   链对象间接调模型。week13 起编排完全交给 LangGraph，节点内直调（`call_llm`）
   让「谁调模型、用什么模板、怎么解析」在节点里一眼可见；LangChain 保留模型抽象
   （BaseChatModel）与提示词模板（ChatPromptTemplate）——两者都是稳定的基础设施，
   而链只是组织方式之一。
2. **为什么状态机里放 `schema` / `execution` 这类大对象？** LangGraph 的 state 就是
   工作流上下文，节点间不共享隐式变量；放进去才能被 checkpointer 一起持久化，
   运行结束后仍能完整回放（`get_state` 拿到的就是当时的全量状态）。
   序列化用带白名单的 `JsonPlusSerializer`（见 `checkpoint.py`），自定义 dataclass
   需要显式登记，避免「未注册类型」警告与未来的严格模式拦截。
3. **为什么默认 memory checkpoint？** 演示项目的重点是「每次运行 = 一个可回查的线程」，
   memory 零依赖、零配置；需要跨重启恢复时一行配置切到 sqlite
   （`langgraph-checkpoint-sqlite` 缺失时自动降级并提示）。
4. **mock 为什么仍做成 `BaseChatModel`？** 让离线模拟与真实模型同接口、同调用路径，
   `call_llm` 对两种模型完全一致，切换零成本；顺带演示了 LangChain 模型抽象的扩展点。
5. **为什么没有做成 ReAct Agent？** 本项目的教学重点是「固定流程的可见性与可控性」——
   七个阶段逐一留痕、六道校验、改写重试回路、双指标评测，都是自主规划 Agent
   不暴露的内部细节。LangGraph 的能力（状态、checkpointer、流式）用在固定流程上，
   恰恰说明「框架价值不以牺牲可控性为代价」。
