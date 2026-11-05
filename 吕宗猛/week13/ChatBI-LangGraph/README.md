# ChatBI · 自然语言问数（LangGraph 版）

week13 作业项目：把 week12 `ChatBI-LangChain` 的手写编排循环显式建模为
**LangGraph StateGraph**，并结合作业 2 提供对话式前端——用户在网页输入文本，
通过对话（含追问）拿到 SQL Agent 的执行结果。

数据集：`db/chinook.db`（Chinook 音乐商店示例库，11 张表，发票日期 2009-01-01 ~ 2013-12-22）。

## 快速开始

```powershell
# 依赖已装入 conda py312 环境（langchain 1.4.7 / langchain-openai 1.7.3 / langgraph 1.2.18）
# 首次运行先准备 .env：copy .env.example .env，再填入与 week12 相同的 BASE_URL / API_KEY
python main.py                       # 或双击 启动.bat
```

打开 <http://127.0.0.1:8613/>（8611 = openai-agents 版，8612 = langchain 版，本版错开端口，三版可同时运行对照）。

## 与 week12（LangChain 版）的对应关系

| 环节 | week12 · LangChain 版 | week13 · LangGraph 版 |
|---|---|---|
| 顶层编排 | `pipeline.py` 手写 for 循环（生成 → 复核 ≤3 轮 → 执行） | `graph.py` `StateGraph`：`check` 节点的**条件边**承担回炉与终止 |
| 单 Agent 工具调度 | `langchain.agents.create_agent`（内部即 langgraph 预置 react 图） | 不变（保留同一封装 `core/llm.py`） |
| 事件产出 | pipeline 里 `yield` | 节点内 `get_stream_writer()` 写 custom 事件，外层 `astream(stream_mode="custom")` 透传 |
| 事件契约 | stage / delta / done / error | **完全一致**（payload 形状、阶段名、耗时字段均不变） |
| 执行调用 | 同步 `run_query`（在 async 上下文里阻塞事件循环） | `asyncio.to_thread` 移入线程池（行为不变，事件循环不阻塞） |
| 对话 | 单轮问答 | **新增**：请求体 `history` 字段 + 生成/复核提示词带追问语境 |

保持不变的部分：`config.py` 变量体系、`core/schema.py`（结构解析）、`core/guard.py`（静态复核）、
`core/executor.py`（只读执行）、`smoke.py`——SSE 事件契约与 week12 完全一致。

## 目录结构

```
ChatBI-LangGraph/
├── main.py                  FastAPI 入口：页面、/api/health、/api/schema、/api/chat/stream
├── config.py                .env 读取：模型、数据库路径、轮次与执行限额（PORT 默认 8613）
├── graph.py                 ★ LangGraph StateGraph：5 节点 + 条件边（本作业核心）
├── pipeline.py              薄封装：组装 initial state、消费 custom 事件流，维持 run_pipeline 签名
├── core/
│   ├── llm.py               ChatOpenAI + create_agent 封装（复用 week12）
│   ├── schema.py            结构解析（复用 week12）
│   ├── guard.py             静态复核（复用 week12，含 pragma_* 表值函数修复）
│   └── executor.py          只读执行（复用 week12）
├── agent/
│   ├── generate_agent.py    Agent A：生成 SQL（新增对话历史注入与提示词追问规则）
│   ├── check_agent.py       Agent B：复核 SQL（新增追问语境；主模型超时自动降级）
│   └── summarize_agent.py   Agent C：结果归纳，astream 流式输出
├── web/                     ★ 对话式前端（index.html / app.js / style.css）
├── db/chinook.db
├── smoke.py                 命令行自测
├── requirements.txt
└── 启动.bat
```

## 流程（LangGraph 图）

```
START ──► parse_schema ──► generate ──► check ──(条件边 route_after_check)
                                             ├─ approved ──► execute ──► summarize ──► END
                                             ├─ fatal / 轮次耗尽 ──► END
                                             └─ 未通过且未超 3 轮 ──► generate（带 feedback）
```

- **parse_schema**：读库结构（缓存），注入 DDL + 外键图 + 真实日期范围。
- **generate**：Agent A 自主调用 `describe_table` / `sample_values` / `search_text` 核实字段与取值，
  `submit_sql` 收口提交；本轮失败/未通过时，下一轮由条件边带着 feedback 回到本节点。
- **check**：静态层（只读白名单、危险操作、聚合缺 GROUP BY、EXPLAIN 校验、LIMIT 兜底、
  pragma_* 表值函数拦截）+ Agent B 语义复核（JOIN 命中真实外键、笛卡尔积、聚合口径、
  时间范围、TopN 方向）。fatal（写操作 / unrecoverable）与轮次耗尽都在本节点发出 error 事件。
- **execute**：只读 URI + authorizer + 超时中断 + 200 行截断。
- **summarize**：仅问题与结果前 6 行交给 Agent C，token 增量经 custom 事件 → SSE 推送。

## 对话与追问（作业 2）

- 前端维护最近几轮问答（问题 / SQL / 归纳答案），随下次请求放在 `history` 字段回传
  （默认最近 3 条，`MAX_HISTORY_TURNS` 可调）。
- Agent A 的提示词增加「对话上下文」规则：上下文只用于理解指代（如「那加拿大呢」「换成 2011 年呢」），
  生成的 SQL 必须是自包含的完整查询，不得引用历史 SQL。
- Agent B 同步收到「追问语境」（上一问 + 上一轮 SQL 摘要），按同一口径复核。

## 配置（.env）

首次运行：`copy .env.example .env`，`BASE_URL` / `API_KEY` / `MODEL_NAME` 与 week12 保持一致
（本仓库不落任何真实密钥）。仅 `PORT=8613` 错开。模型分工、复核降级（`CHECK_FALLBACK_MODEL`）、
执行限额、`MAX_HISTORY_TURNS` 等同名变量含义不变。

## 验证记录（2026-11-05，py312 + langgraph 1.2.18，飞牛网关 192.168.124.88:7863）

### smoke（命令行完整流程）

| 问题 | 生成 | 复核 | 执行 | 归纳 | 总耗时 | tokens |
|---|---:|---:|---:|---:|---:|---:|
| 2010 年各国销售额前 5 名，并给出订单数 | 6.9s | 8.7s | 2ms | 1.9s | 18.8s | 17,648 |

一轮通过；答案与 week12 口径一致（USA 102.98 / 18 单）。

### SSE 端到端（对话式前端同契约）

| 场景 | 结果 |
|---|---|
| 正常问答（2010 年各国销售额前 5 名） | 1 轮通过，26.4s，17,198 tokens，5 行结果，事件序列 schema→generate→check→execute→summarize→done 完整 |
| **追问**「那加拿大 2010 年的订单数是多少」 | **跨轮上下文生效**：Agent A 依据历史正确理解指代，生成自包含 SQL（`WHERE BillingCountry='Canada' AND 2010 年`），1 轮通过 14.6s，答案 12 笔 / 76.26 与上一问数据吻合 |
| 危险请求「删除 customers 表中的所有数据」 | 生成 Agent 自审后改交只读 SELECT，复核 Agent 判 `unrecoverable`，**第 1 轮 fatal 终止（14.5s），未执行任何写操作** |

### 浏览器 CDP 端到端（headless Chrome，2026-11-05）

真实浏览器加载页面并连续三轮对话，7 项断言全 PASS、零 JS 异常、零 4xx：

| 断言 | 结果 |
|---|---|
| 问 1 五阶段徽章全部 done、答案含 102.98、SQL + 5 行表格渲染 | PASS |
| 问 2（追问「那加拿大 2010 年的订单数」）1 轮通过、答案 12 单 / 76.26 | PASS |
| 问 3 危险请求只读拒绝终止（复核 error，无执行无归纳） | PASS |

验证过程发现并修复的两个前端缺陷：阶段徽章 `pills` 标识符笔误（首个事件即抛错）、
结果表格依赖 done 事件的 columns/rows（实际在 execute 阶段事件里，需暂存）。

### 结构验证（网关就绪前完成）

- 12 个 py 文件 `py_compile` 通过；`build_graph()` 拓扑正确（parse_schema / generate / check / execute / summarize + 条件边）。
- 网关故障注入（本机误配 127.0.0.1:7863 时）：每轮 generate 捕获网关错误 → 带反馈回炉 → 3 轮耗尽发 error 终止，SSE 事件序列与耗时统计全程正确，服务不崩溃。

## 安全边界

与 week12 完全一致（复用同一套 `guard.py` / `executor.py`）：只读 URI 物理不可写、
authorizer 二次拦截、静态白名单、EXPLAIN 校验、5s 超时、200 行上限、
可修复/不可修复复核失败区分处理。

## 自测

```powershell
python smoke.py "2010 年各国销售额前 5 名" "哪位员工负责的客户最多"
```
