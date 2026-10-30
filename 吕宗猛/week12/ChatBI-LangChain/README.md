# ChatBI · 自然语言问数（langchain 版）

与 `week11/Week11-ChatBI`（openai-agents 版）功能相同的 langchain 改写版：
用户用中文提问，系统解析数据库结构 → langchain Agent 生成 SQL → 复核（静态 + Agent，最多 3 轮）→ 只读执行 → 流式归纳。页面实时展示每个阶段的状态与耗时。

数据集：`db/chinook.db`（Chinook 音乐商店示例库，11 张表，发票日期 2009-01-01 ~ 2013-12-22）。

## 快速开始

```powershell
# 依赖已装入 conda py312 环境（langchain 1.4.7 / langchain-openai 1.7.3 / langgraph 1.2.18）
python main.py                       # 或双击 启动.bat
```

打开 <http://127.0.0.1:8612/>（原版用 8611，本版错开端口，两版可同时运行对照）。

## 与原版（openai-agents）的对应关系

| 原语 | openai-agents 版 | langchain 版 |
|---|---|---|
| 模型接入 | `AsyncOpenAI` + `OpenAIChatCompletionsModel` | `langchain_openai.ChatOpenAI`（同一网关） |
| Agent 循环 | `Agent` + `Runner.run` | `langchain.agents.create_agent`（框架自动调度工具） |
| 工具定义 | `@function_tool` + `RunContextWrapper` | `langchain_core.tools.@tool` |
| 收口停止 | `StopAtTools(stop_at_tool_names=[...])` | 收口工具写入本请求 store 容器；模型提交后按提示词直接输出确认语，不再发起工具调用，agent 自然结束 |
| 工具轨迹 | `RunResult.new_items` | 逐条 `AIMessage.tool_calls` 收集 |
| token 用量 | `context_wrapper.usage` | 逐条 `AIMessage.usage_metadata` 累加（流式为末 chunk 的 `usage_metadata`） |
| 流式归纳 | `Runner.run_streamed` | `ChatOpenAI.astream()` |

保持不变的部分：`config.py`、`core/schema.py`（结构解析）、`core/guard.py`（静态复核）、
`core/executor.py`（只读执行）、`pipeline.py`（编排与 SSE 事件形状）、`web/`（前端）、
`main.py`、`smoke.py`——**对外 API 与事件契约与原版完全一致，前端零改动**。

## 目录结构

```
ChatBI-LangChain/
├── main.py                  FastAPI 入口：页面、/api/health、/api/schema、/api/chat/stream
├── config.py                .env 读取：模型、数据库路径、轮次与执行限额
├── pipeline.py              流程编排：阶段事件、耗时、最多 3 轮复核
├── core/
│   ├── llm.py               ChatOpenAI + create_agent 封装：运行、计时、用量归一、工具轨迹
│   ├── schema.py            结构解析（复用原版）
│   ├── guard.py             静态复核（复用原版）
│   └── executor.py          只读执行（复用原版）
├── agent/
│   ├── generate_agent.py    Agent A：生成 SQL（工具：list_tables / describe_table / sample_values / search_text；submit_sql 收口）
│   ├── check_agent.py       Agent B：复核 SQL（validate_sql + submit_review 收口；主模型超时自动降级）
│   └── summarize_agent.py   Agent C：结果归纳，astream 流式输出
├── web/                     单页前端（与原版相同，零改动）
├── db/chinook.db
├── smoke.py                 命令行自测
├── requirements.txt
└── 启动.bat
```

## 流程

与原版一致：

```
① 结构解析（缓存） ──► ② Agent A 生成 SQL ──► ③ 复核 ──┬─ 通过 ─► ④ 只读执行 ─► ⑤ 流式归纳
                                       ▲                │
                                       └── 未通过，带问题清单重试（≤3 轮）◄┘
```

- **② 生成**：Agent A 注入完整 DDL + 外键图 + 真实日期范围；模型自主决定调用
  `describe_table` / `sample_values` / `search_text` 核实字段与取值，由 langgraph
  循环自动执行工具并回填结果；最后调用 `submit_sql` 收口提交。
- **③ 复核**：静态层（只读白名单、危险操作、聚合缺 GROUP BY、EXPLAIN 校验、LIMIT 兜底）
  + Agent B 语义复核（JOIN 命中真实外键、笛卡尔积、聚合口径、时间范围、TopN 方向）。
- **④ 执行**：只读 URI + authorizer + 超时中断 + 200 行截断。
- **⑤ 归纳**：仅问题与结果前 6 行交给 Agent C，token 增量经 SSE 推送。

## 配置（.env）

与原版一致，仅 `PORT=8612` 错开。模型分工、复核降级（`CHECK_FALLBACK_MODEL`）、
执行限额等全部同名变量，含义不变。

## 实测数据（2026-10-29，py312 + langchain 1.4.7，同一网关）

| 问题 | 生成 | 复核 | 执行 | 归纳 | 总耗时 | tokens |
|---|---:|---:|---:|---:|---:|---:|
| 2010 年各国销售额前 5 名，并给出订单数 | 5.6s | 6.5s | 2ms | 1.5s | 15.03s | 16,818 |
| 哪位员工负责的客户最多 | 5.7s | 5.6s | 2ms | 1.6s | 13.02s | 16,370 |
| Rock 流派最贵的 5 首歌 | 7.0s | 7.0s | 3ms | 1.3s | 15.27s | 17,290 |
| 消费金额最高的 10 位客户（SSE 端到端） | 5.1s | 6.6s | 2ms | 1.5s | 14.59s | 16,714 |

均为一轮通过；答案与原版一致（USA 102.98/18 单、Jane Peacock 21 位客户、
Helena Holý 49.62 等）。

与原版（openai-agents，2026-10-22 实测）对比：总耗时相当或略优（15.0 vs 22.6 /
13.0 vs 14.7 / 15.3 vs 20.9，网关波动范围内），token 用量偏高约 1.3~2.3 倍
——langchain 版收口工具提交后模型多一轮确认应答，且每轮对话都重复携带完整
system prompt（结构信息约 1.3k tokens），属框架形态差异，非实现缺陷。

危险请求「删除 customers 表中的所有数据」：与原版同路径——生成 Agent 自审后
改交只读 SELECT，复核 Agent 判 `unrecoverable`（只读系统无法执行写操作），
**第 1 轮终止（12.1s），未执行任何写操作**。

浏览器端到端：SSE 事件序列完整（5 阶段 stage + 93 个 delta 增量 + done），
页面各区域（数据集/模型编排/表结构/示例问题/结果表格）渲染正常。

## 安全边界

与原版完全一致（复用同一套 `guard.py` / `executor.py`）：只读 URI 物理不可写、
authorizer 二次拦截、静态白名单、EXPLAIN 校验、5s 超时、200 行上限、
可修复/不可修复复核失败区分处理。

## 已知限制

- 网关不支持 `response_format=json_schema`，结构化结果仍用收口工具获取（langchain 版
  保留了文本解析兜底）。
- langchain 收口形态比 openai-agents 的 `StopAtTools` 多一轮模型确认应答（约 1~2s、
  数百 tokens）——这是「框架自动调度工具」的自然代价。
- 其余限制（单轮问答、仅适配 SQLite、归纳只读前 6 行等）与原版相同。

## 修复记录

### 2026-10-29 · PRAGMA 表值函数绕过三层复核（实测发现）

**现象**：问「albums 表有哪些字段」时模型生成 `SELECT * FROM pragma_table_info('albums')`，
静态层、validate_sql 工具、复核模型三层全部放行，真实执行期被 authorizer 拒绝，
流程以 `DatabaseError: not authorized` 终止。

**根因**：SQLite 对 `pragma_table_info()` 表值函数的 `SQLITE_PRAGMA` 检查发生在
**执行期**而非编译期——EXPLAIN 探不到；静态白名单 `\bpragma\b` 又匹配不上
`pragma_table_info`（`_` 属于 `\w`，词边界断不开）。

**修复**（四项，只改本版）：

1. `core/guard.py`：静态层新增确定性规则，`pragma_*` 表值函数判为**可修复错误**
   （回炉改写，非 fatal）；语句级 PRAGMA 仍维持 fatal。
2. `agent/generate_agent.py`：提示词 SQL 规范禁止 PRAGMA 语句与 pragma_* 表值函数。
3. `agent/check_agent.py`：复核清单新增第 6 条——出现 pragma_* 表值函数一律 approved=false。
4. `core/executor.py`：执行期 authorizer 拒绝转为可读信息（「触发只读安全策略」），不再裸抛。

**回归验证**：bug SQL 被静态层拦截并回炉；语句级 PRAGMA 仍 fatal；正常查询与
含 `prog` 字样的字符串不误伤；聚合缺 GROUP BY 原规则正常；诱发问题
「albums 表有哪些字段」第 1 轮即通过（模型改用 describe_table 工具 + 常量 UNION ALL）；
原有问题与危险请求路径无回归。

## 自测

```powershell
python smoke.py "2010 年各国销售额前 5 名" "哪位员工负责的客户最多"
```
