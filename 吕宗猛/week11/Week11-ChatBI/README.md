# ChatBI · 自然语言问数

基于 SQLite 的 ChatBI 演示项目：用户用中文提问，系统解析数据库结构 → 由 Agent 生成 SQL → 复核（字段、主外键联查、危险操作，最多 3 轮）→ 只读执行 → 用自然语言流式归纳结果。页面实时展示每个阶段的状态与耗时。

数据集：`db/chinook.db`（Chinook 音乐商店示例库，11 张表，发票日期 2009-01-01 ~ 2013-12-22）。

## 快速开始

```powershell
conda activate py312
pip install -r requirements.txt      # 当前环境已装齐
python main.py                       # 或双击 启动.bat
```

打开 <http://127.0.0.1:8611/>，在输入框提问（Enter 发送，Shift+Enter 换行）。

双击 `启动.bat` 时若端口已被占用（例如服务已在运行），会打印中文提示并直接打开页面，不会抛 WinError 10048；控制台日志已关闭 ANSI 颜色码，避免 Windows 下显示成 `[32mINFO[0m` 这类乱码。

## 目录结构

```
Week11-ChatBI/
├── main.py                  FastAPI 入口：页面、/api/health、/api/schema、/api/chat/stream
├── config.py                .env 读取：模型、数据库路径、轮次与执行限额
├── pipeline.py              流程编排：阶段事件、耗时、最多 3 轮复核
├── core/
│   ├── schema.py            结构解析：表/字段/类型/主键/外键/索引/行数/日期范围 → Prompt
│   ├── guard.py             静态复核：单语句、只读白名单、危险操作、聚合缺 GROUP BY、EXPLAIN 校验、LIMIT 兜底
│   ├── executor.py          只读执行：mode=ro&immutable=1、authorizer、超时中断、行数上限、字段取值探查
│   └── llm.py               AsyncOpenAI + OpenAIChatCompletionsModel，计时与 token 用量
├── agent/
│   ├── generate_agent.py    Agent A：生成 SQL（工具：list_tables / describe_table / sample_values / search_text；submit_sql 收口）
│   ├── check_agent.py       Agent B：复核 SQL（工具：validate_sql / submit_review 收口；主模型超时自动降级）
│   └── summarize_agent.py   Agent C：结果归纳，token 流式输出
├── web/                     单页前端（原生 HTML/CSS/JS，无构建）
├── db/chinook.db
├── smoke.py                 命令行自测：逐问打印各阶段耗时
└── 启动.bat
```

## 流程

```
① 结构解析（缓存） ──► ② Agent A 生成 SQL ──► ③ 复核 ──┬─ 通过 ─► ④ 只读执行 ─► ⑤ 流式归纳
                                       ▲                │
                                       └── 未通过，带问题清单重试（≤3 轮）◄┘
```

- **② 生成**：Agent A 注入完整 DDL + 外键图 + 真实日期范围；可调用工具查字段、抽样取值、全文模糊搜索，避免拼错字段或把中文取值硬套英文库。
- **③ 复核**：两层。
  1. 静态层（确定性）：只允许单条 `SELECT/WITH`；拒绝 INSERT/UPDATE/DELETE/DDL/PRAGMA/ATTACH/事务语句；检测聚合查询缺 `GROUP BY`；用 `EXPLAIN` 让 SQLite 自身校验表名与字段名；无 `LIMIT` 时自动补 200。
  2. 模型层（Agent B）：核对 JOIN 是否命中真实外键、是否漏 ON 造成笛卡尔积、聚合口径、时间范围、TopN 方向等语义问题；`validate_sql` 提供事实依据。
- **④ 执行**：独立只读连接（`file:...?mode=ro&immutable=1`）+ `authorizer` 二次拦截 + `progress_handler` 超时中断 + 结果截断。
- **⑤ 归纳**：仅把问题与结果前 6 行交给 Agent C，约束为 2~4 句、无表格无代码，token 增量经 SSE 推送到页面。

## 配置（.env）

| 变量 | 说明 | 默认 |
|---|---|---|
| `BASE_URL` / `API_KEY` | OpenAI 兼容网关地址与密钥 | — |
| `MODEL_NAME` | 兜底模型 | `cn:deepseek-v4.1-flash` |
| `GENERATE_MODEL` | 生成模型 | 同 `MODEL_NAME` |
| `CHECK_MODEL` | 复核模型 | 同 `MODEL_NAME` |
| `SUMMARY_MODEL` | 归纳模型 | 同 `MODEL_NAME` |
| `CHECK_FALLBACK_MODEL` | 复核主模型超时/异常时的备用模型 | `cn:minimax-m3.1-flash` |
| `CHECK_TIMEOUT_SECONDS` | 复核单次超时 | `15` |
| `DB_FILE_PATH` | SQLite 路径 | `./db/chinook.db` |
| `MAX_REVIEW_ROUNDS` | 最大复核轮数 | `3` |
| `MAX_RESULT_ROWS` | 结果行数上限 | `200` |
| `QUERY_TIMEOUT_SECONDS` | 查询执行超时 | `5` |
| `PORT` | 服务端口 | `8611` |

## 实测数据（2026-10-22，本机 py312，网关延迟波动存在）

| 问题 | 生成 | 复核 | 执行 | 归纳 | 总耗时 | tokens |
|---|---:|---:|---:|---:|---:|---:|
| 2010 年各国销售额前 5 名，并给出订单数 | 8.19s | 11.49s | 1ms | 2.89s | 22.61s | 12,589 |
| 消费金额最高的 10 位客户 | 5.21s | 6.77s | 2ms | 4.36s | 16.34s | 7,438 |
| 各音乐流派的曲目数量排行 | 7.01s | 6.54s | 3ms | 3.74s | 17.29s | 7,139 |
| 哪位员工负责的客户最多 | 5.57s | 6.60s | 1ms | 2.52s | 14.69s | 6,676 |
| Rock 流派最贵的 5 首歌 | 8.62s | 9.21s | 2ms | 3.10s | 20.93s | 9,666 |

均为一轮通过。浏览器端到端（含首屏加载）实测 29.4s，其中服务端流程 17.44s。

危险请求「删除 customers 表中的所有数据」：两条路径都在**第 1 轮**终止，均未执行任何写操作。

- 模型直接写出 `DELETE/COMMIT`：静态层一次报全「危险操作 + 事务语句 + 多语句」，判为不可修复，约 6s 结束；
- 模型自审后改给只读统计脚本：复核 Agent 判定 `unrecoverable`（诉求在只读系统中无解），约 8~13s 结束。

早期实现对所有复核失败一律重试，该场景会跑满 3 轮（40~90s）且必然失败；现已区分「可修复」与「不可修复」，实测 8.2s 终止。

复核模型 A/B（同一批 3 条问题 SQL）：

| 用例 | minimax-m3.1-flash | deepseek-v4.1-flash |
|---|---|---|
| 笛卡尔积缺 ON | 10.2s，命中 | 4.4s，命中 |
| 聚合缺 GROUP BY | 6.8s，**漏判** | 4.8s，命中 |
| 缺少年份过滤 | 24.4s，命中 | 7.0s，命中 |

据此默认复核模型改用 `deepseek-v4.1-flash`，并保留 `minimax` 作为超时降级选项；同时在静态层补了确定性的「聚合缺 GROUP BY」校验，不依赖模型。

## 安全边界

- 数据库以只读 URI 打开，物理上不可写；执行连接额外安装 `authorizer` 拦截写动作。
- 静态白名单只放行 `SELECT/WITH`，多语句、DDL、PRAGMA、ATTACH 等一律拒绝。
- SQL 由 SQLite 通过 `EXPLAIN` 实际编译校验，字段名/表名错误在复核阶段即暴露。
- 复核失败分两类：字段名、聚合缺 `GROUP BY`、语法等可修复错误回炉重试（≤3 轮）；写操作/非查询语句由静态层一次判死，诉求本身不可满足的由复核 Agent 标记 `unrecoverable` 立即终止，不做无意义重试。
- 结果集上限 200 行、查询 5s 超时，避免拖垮页面。
- 3 轮复核仍未通过则终止，不做「降级执行」。

## 已知限制

- 网关不支持 `response_format=json_schema`（实测被静默忽略），因此结构化结果统一用「收口工具」（`submit_sql` / `submit_review`）获取，并保留文本解析兜底。
- 模型存在尾延迟（复核曾出现 48s 单次），已加超时降级；总耗时仍会随网关波动。
- 当前为单轮问答，不保留多轮上下文；追问需重新描述。
- 「诉求不可满足」由复核模型判断，存在小概率漏标；漏标时退回 3 轮上限，但仍不会执行写操作。
- 归纳只读取前 6 行结果，回答中的「前几名」以此为准；完整数据在页面的执行阶段表格中。
- 仅适配 SQLite；换成 MySQL/PostgreSQL 需替换 `schema.py` 与 `executor.py` 的方言部分。

## 自测

```powershell
python smoke.py "2010 年各国销售额前 5 名" "哪位员工负责的客户最多"
```
