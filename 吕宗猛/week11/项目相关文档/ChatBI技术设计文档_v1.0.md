# ChatBI 技术设计文档

- 文档版本：v1.0
- 文档状态：技术设计评审稿；不代表已实现、已测试、已部署或获准上线
- 编写日期：2026-10-22
- 需求基线：`ChatBI功能设计文档_v1.0.md`（REQ-01–REQ-43、DEC-01–DEC-22）
- 技术决策来源：2026-10-22 grill 会话锁定的 TD-01–TD-07
- 目标读者：项目负责人、开发、测试、安全、DBA、运维、产品

> 阅读约定：本文中的 DDL、伪代码、配置片段、容量数字均为**设计示例**，未在真实 MySQL、Redis、Celery、模型供应商或 Docker 环境验证。标注【已决策】的条目是本次 grill 明确选择的技术主线；标注【推荐】的条目仍需评审；标注【待决策】的条目不得默认关闭。

---

## 1. 文档信息、依据、状态与术语

### 1.1 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | ChatBI 技术设计文档 |
| 版本 | v1.0 |
| 状态 | 技术设计评审稿 |
| 编写日期 | 2026-10-22 |
| 需求依据 | `ChatBI功能设计文档_v1.0.md`，REQ-01–REQ-43 |
| 背景依据 | `ChatBI项目设计文档_初稿_v0.1.md`，仅用于背景与早期设想 |
| 技术决策依据 | 2026-10-22 grill 会话，TD-01–TD-07 |
| 交付性质 | 仅文档设计；不含代码实现、数据库连接、模型调用、容器部署或生产变更 |
| 评审对象 | 架构、权限、SQL 安全、任务可靠性、数据模型、接口、部署与测试方案 |

### 1.2 编写依据与优先级

1. **功能设计文档 v1.0** 是唯一需求基线。本文所有“已确认”表述均可回溯到其中的 REQ 编号。
2. **项目设计初稿 v0.1** 只用于理解背景。与功能设计文档冲突时，以功能设计文档为准。
3. **2026-10-22 grill 决策**是本次技术主线。它只解决“怎么做”，不替代业务规则、安全策略或 DBA 结论。
4. **技术设计编写计划**规定了章节范围与交付边界，本文按其第 6 节目录展开。

**范围声明（TC-01）**：本轮不参考 `Week11-ChatBI` 目录下的代码、README、依赖文件、数据库文件或既有测试记录。本文不描述现有实现差距、代码复用或迁移路径；文中目录、表名、接口均为独立设计建议，不对现有工程结构构成约束。

### 1.3 状态标记

| 标记 | 含义 | 处理规则 |
| --- | --- | --- |
| 【已确认】 | 功能设计文档中用户明确确认的需求 | 不得在技术设计中静默削弱 |
| 【已决策】 | 2026-10-22 grill 中用户明确选择的技术主线 | 后续变更走变更记录，不重新讨论已关闭分支 |
| 【推荐】 | 尚未获批、但建议采用的实现方案 | 评审可改；不得表述为用户已确认 |
| 【待决策】 | 业务规则、参数、环境或安全策略仍缺输入 | 保留编号与影响，不猜测答案 |
| 【设计示例】 | DDL、伪代码、配置、容量数字 | 必须经真实环境验证后才可投产 |

### 1.4 术语

| 术语 | 定义 |
| --- | --- |
| SQP | Semantic Query Plan，语义查询计划；模型输出或规则生成的结构化查询意图，不含可执行 SQL 文本 |
| AST | Abstract Syntax Tree，抽象语法树；本文特指 sqlglot 解析 MySQL 方言后得到的语法树 |
| 有效权限 | 角色模板、用户例外、固定行范围与敏感策略合成后的最终权限集合 |
| 权限纪元 | 全局单调递增的权限版本号；任何权限变更使其递增，用于缓存失效与检查点比对 |
| 行范围包装 | 将受行权限约束的基表替换为带固定谓词的派生表，保证连接、聚合、子查询前已完成行过滤 |
| 范围证明 | 结果快照中足以证明“每一行/每个聚合组都在接收者当前范围内”的血缘信息 |
| 任务租约 | worker 对 `query_task` 的有期限独占标记；过期可被回收，避免任务永久卡死 |
| Outbox | 与业务事务同库提交的待投递消息表；由独立分发器投递到 Celery，解决“提交成功但消息丢失” |
| 物理取消 | 数据库侧确认查询已停止；与“应用逻辑已停止”分开记录 |
| 降级 | 依赖不可用时保留已授权能力、减少非关键能力，而不是伪造结果 |

### 1.5 交付边界

- 本文不包含：代码仓库、可执行脚本、真实密码/密钥、服务器地址、生产库连接串、模型供应商合同结论。
- 本文不证明：性能目标已达成、安全测试已通过、备份可恢复、供应商合规已批准。
- 本文中的接口路径、表名、字段名、错误码均为建议契约；冻结前需接口评审与 DBA 评审。
- 任何生产接入、数据迁移、容器部署、账号创建均需另立实施计划并获得批准。

---

## 2. 需求约束、技术目标与设计边界

### 2.1 需求到技术的硬约束

| 需求约束 | 来源 | 技术含义 | 主要章节 |
| --- | --- | --- | --- |
| 单个生产 MySQL，20–100 张表，只读 | REQ-01 | 单数据源适配、只读账号、结构采集与执行分离 | 4、10、11 |
| 初期约 10–50 人 | REQ-02 | 模块化单体足够；不引入 Kubernetes/微服务 | 4、5、19 |
| 独立用户体系、管理员开通 | REQ-03、REQ-13 | 自建认证、部门/角色、无自助注册 | 6 |
| 自然语言问数、动态 Schema 检索 | REQ-04 | 检索服务 + 语义层 + 受控 SQL 生成 | 7、10 |
| 回答、表格、图表；普通用户不见 SQL | REQ-05、REQ-06 | 结果契约与前端渲染分离；SQL 仅后台审计可见 | 13、16 |
| 多轮追问、固定窗口、条件纠正 | REQ-07–REQ-11 | 结构化查询状态 + 消息窗口分离 | 8 |
| 取消、有限重试 | REQ-12 | 持久任务、租约、预算、物理取消分离反馈 | 9、11 |
| 角色模板 + 用户例外；表/字段/行权限 | REQ-14–REQ-18 | 权限合成引擎、权限纪元、检查点 | 6 |
| 长期历史、手动删除、快照/重查共享 | REQ-19–REQ-24 | 历史、快照、共享、文件四类对象分离 | 14 |
| 元数据每日同步、术语、外键、指标、主题 | REQ-25–REQ-30 | 物理元数据与业务语义分层、版本化 | 7 |
| 多模型按用途配置、主备、后台密钥 | REQ-31–REQ-33 | 模型网关、路由、熔断、密钥加密 | 12 |
| 查询审计、管理日志、监控告警 | REQ-34、REQ-36 | 审计事件模型、指标、告警 | 18 |
| 用户/全局限流、超时、行数、并发 | REQ-35 | Redis 令牌桶 + 执行器硬限制 | 11、17 |
| Linux + Compose、内网 HTTPS、完整备份 | REQ-37–REQ-39 | Nginx + Compose + 受控卷 + 备份恢复 | 19、20 |
| 常规查询初始目标 5–10 秒 | REQ-40 | 端到端预算与压测口径，不写成 SLA | 17 |
| 云端默认不收原始明细 | REQ-41 | 外发数据最小化、摘要白名单、程序拦截 | 12、13 |
| 全面功能/安全/性能/恢复验收 | REQ-42 | 测试矩阵与上线阻断项 | 21、23 |
| 受控 Excel 导出 | REQ-43 | 异步导出、公式注入防护、下载再授权 | 14 |

### 2.2 技术目标

| 编号 | 目标 | 可验证方式 | 备注 |
| --- | --- | --- | --- |
| G-01 | 所有进入业务库的 SQL 均经过同一 AST 安全门 | 代码路径唯一 + 负向测试集 100% 拒绝 | 不以“模型已判断安全”替代 |
| G-02 | 受支持语法下，行权限无绕过路径 | 两部门测试库 + 别名/JOIN/子查询/UNION/CTE 用例 | 不支持语法必须拒绝 |
| G-03 | 权限变更在下一个请求生效 | 权限纪元比对 + 交付前复核用例 | 已下载文件不可撤回 |
| G-04 | 任务状态在 API/worker 重启后可恢复 | 杀进程/重启演练 + 租约回收 | 不自动重跑未知执行 |
| G-05 | 原始明细默认不出内网 | 出站请求捕获 + 字段白名单断言 | 摘要也需规则 |
| G-06 | 常规查询 5–10 秒目标可测量 | 固定问题集 + 分阶段耗时 + P50/P95 | 以压测为准，不作承诺 |
| G-07 | 任一结果可追溯到任务、attempt、权限/语义版本 | trace_id 贯穿日志、审计、结果 | 普通用户不见 SQL |
| G-08 | 部署可重复、可回滚、可备份恢复 | Compose 重建 + 恢复演练 | 需真实环境验证 |

### 2.3 非目标

- 不支持多数据源、跨库查询、联邦查询。
- 不支持业务库写入、DDL、存储过程、事务控制或任何数据变更。
- 不提供公开链接共享、部门共享、自助注册、企业 SSO（第一版）。
- 不提供用户自定义行级范围；范围固定为本人及所属部门（具体语义见 DEC-04）。
- 不强制引入向量数据库、Kubernetes、RabbitMQ 或独立对象存储。
- 不承诺模型生成的 SQL 字符串与业务专家 SQL 逐字一致；验收比较业务口径与结果。
- 不把“只读账号”解释为“对生产无负载影响”。

### 2.4 设计原则

1. **Fail-closed**：无法证明权限完整、语法受支持、成本可控时拒绝，不猜测、不放宽。
2. **数据库为权威**：任务、权限、元数据、审计以应用 MySQL 为事实源；Redis 只做缓存、限流、会话与消息通道。
3. **模型不可信**：模型输出是候选输入，不是授权、不是安全结论、不是最终 SQL。
4. **检查点前置且重复**：受理、执行前、发布前、共享打开、下载前均重新校验。
5. **数据最小化**：云端只收必要问题、最小 Schema、必要摘要；原始明细不出内网。
6. **可观察**：每个阶段有状态、耗时、错误类别与 trace_id；拒绝也有审计。
7. **可回滚**：配置、镜像、数据库迁移均保留上一版本；破坏性变更先备份。

---

## 3. 技术决策、选型与替代方案

### 3.1 决策总表

| 编号 | 决策 | 选择 | 状态 | 主要影响 |
| --- | --- | --- | --- | --- |
| TD-01 | 后端运行时 | Python 3.12 + FastAPI + Pydantic v2 | 【已决策】 | 语言、异步模型、SQL 解析生态 |
| TD-02 | 应用数据库 | MySQL 8.0+（InnoDB、utf8mb4） | 【已决策】 | 事务、任务表、审计、迁移 |
| TD-03 | 任务编排 | 应用 MySQL 任务表为权威；Celery + Redis 仅分发 | 【已决策】 | 可靠性、取消、重试、对账 |
| TD-04 | SQL 安全 | 语义层 + sqlglot AST 校验与改写 | 【已决策】 | 所有查询的唯一安全门 |
| TD-05 | 认证会话 | 服务端会话 + HttpOnly/Secure Cookie + CSRF | 【已决策】 | 撤销、权限即时生效 |
| TD-06 | 前端 | Vue 3 + TypeScript + Vite + Element Plus + ECharts | 【已决策】 | 页面、图表、契约生成 |
| TD-07 | Celery broker | Redis 7 | 【已决策】 | 组件数量、投递语义 |
| TD-08 | 模型接入 | OpenAI-compatible 协议抽象 + 供应商适配器 | 【推荐】 | 多模型、主备、密钥 |
| TD-09 | 快照与导出文件存储 | 本地受控卷（后续可替换对象存储） | 【推荐】 | 容量、备份、下载鉴权 |
| TD-10 | 部署形态 | Docker Compose + Nginx 反向代理 | 【推荐；REQ-37/38 已确认】 | 网络、证书、持久化 |
| TD-11 | 可观测性 | Prometheus 指标 + 结构化 JSON 日志 | 【推荐】 | 告警、排障、审计 |
| TD-12 | 测试栈 | pytest + Testcontainers + Playwright + k6 | 【推荐】 | 回归、E2E、压测 |
| TD-13 | 数据访问 | SQLAlchemy 2.0 + Alembic；API 异步、worker 同步流式 | 【推荐】 | 事务、迁移、流式读取 |
| TD-14 | API 风格 | REST + SSE（轮询降级） | 【推荐】 | 任务状态、结果推送 |
| TD-15 | 精确版本锁定 | 评审时锁定版本并生成锁文件 | 【待决策】 | 可重复构建、升级回归 |

### 3.2 本次 grill 锁定记录

| 轮次 | 问题 | 用户选择 | 被否决的选项 | 设计后果 |
| --- | --- | --- | --- | --- |
| Q1 | 后端运行时 | Python 3.12 + FastAPI | Java 17 + Spring Boot；Node 20 + NestJS | sqlglot、模型 SDK、异步 IO 作为主线 |
| Q2 | 应用库 | MySQL 8.0+ | PostgreSQL 16；SQLite | 单一数据库栈；使用 SKIP LOCKED、JSON、CTE |
| Q3 | 任务编排 | Celery + Redis；MySQL 任务表权威，Celery 仅分发 | 纯 DB worker；Redis Streams；Celery 全权管理状态 | 需要 Outbox、幂等消费、租约与对账 |
| Q4 | SQL 安全 | 语义层 + sqlglot AST 校验改写 | 数据库视图；正则白名单 + 人工复核 | 查询计划优先、SQL 兜底；统一 AST 安全门 |
| Q5 | 认证会话 | 服务端会话 + HttpOnly Cookie | JWT + 刷新令牌；反向代理可信头 | Redis 会话、CSRF、权限纪元校验 |
| Q6 | 前端 | Vue 3 + TS + Vite + Element Plus + ECharts | React + Ant Design；服务端模板 + HTMX | OpenAPI 生成 TS 类型；Element Plus 管理页 |
| Q7 | Celery broker | Redis | RabbitMQ | 复用 Redis；以 DB 状态与幂等抵消投递风险 |

**与编写计划 TC-04 的差异说明**：编写计划曾建议“MySQL 任务表 + 独立 Python worker”，本次 grill 选择 Celery 作为执行分发。两者不冲突：**任务状态、状态迁移、取消、审计仍以应用 MySQL 为唯一权威**；Celery 只负责“把可执行任务唤醒到某个 worker”，其消息丢失、重复投递、worker 崩溃均由 DB 状态机、Outbox 与幂等消费兜底。该边界写入 §9，任何后续实现不得把 Celery result backend 当作业务状态源。

### 3.3 关键选型说明

#### 3.3.1 Web/API 运行时

- FastAPI 提供 OpenAPI 3.1 契约、Pydantic v2 校验、依赖注入与异步请求处理。
- API 进程使用 `uvicorn`（多 worker 由容器编排或 Gunicorn 管理），只处理 HTTP/SSE，不执行长 SQL。
- 业务库执行使用**同步驱动 + 流式游标**，放在 worker 的线程池中；API 不直接持有业务库长连接。
- 应用库访问使用 SQLAlchemy 2.0；迁移用 Alembic；所有迁移必须可向前兼容一个版本，支持滚动回滚。

#### 3.3.2 应用数据库

- MySQL 8.0+，InnoDB，`utf8mb4_0900_ai_ci`，`DATETIME(3)` 统一 UTC 存储。
- 使用 `JSON` 保存结构化条件、结果摘要、图表配置；JSON 字段不承担强约束，关键字段仍落列。
- 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 做任务领取；使用 `GET_LOCK` 仅用于短临界区，不用于长任务。
- 不使用 MySQL 分区作为第一版必需项；审计表按时间索引，容量增长后再评估分区或归档。

#### 3.3.3 任务编排

- Celery 5.x，Redis 7 作为 broker；`task_ignore_result=True`，不把 result backend 当状态源。
- `acks_late=True`、`task_reject_on_worker_lost=True`、`worker_prefetch_multiplier=1`，降低“消息已预取但 worker 崩溃”的丢失窗口。
- 每个业务任务有 `task_id`（业务 ID）与 `dispatch_id`（Celery 消息 ID）；两者在多对一表中绑定，重复投递按业务 ID 幂等。
- 定时任务（元数据同步、清理、对账）使用 Celery Beat，但 Beat 只投递“触发器”，实际执行仍写 DB 任务表并走同一状态机。

#### 3.3.4 SQL 安全

- 语义层负责“可用表、可用字段、可用关联、指标口径、主题范围”的白名单与编译。
- sqlglot 负责 MySQL 方言解析、AST 结构校验、标识符解析、行谓词包装与重写后复验。
- 两条生成通道：**计划优先**（模型输出 SQP JSON，服务端编译 SQL）与**SQL 兜底**（模型输出 SQL，必须通过完整 AST 门）。两条通道最终都经过同一 `SqlGate`。
- 任何解析失败、未知表/字段、未支持语法、无法证明行范围、成本超限，均返回明确拒绝码，不进入执行。

#### 3.3.5 认证与会话

- 会话 ID 为 256-bit 随机值，Base64url 编码；Cookie 名 `__Host-chatbi_session`，`HttpOnly`、`Secure`、`SameSite=Lax`、`Path=/`。
- 会话数据存 Redis：`sess:{id}` → `{user_id, perm_epoch, created_at, last_seen_at, ip_hash, ua_hash}`，TTL 滑动续期，绝对上限另设。
- CSRF 使用双提交：`chatbi_csrf` 非 HttpOnly Cookie + `X-CSRF-Token` 请求头；所有非 GET/HEAD 请求校验。
- 密码使用 Argon2id；登录失败统一提示；锁定与重置策略仍属 DEC-01。

#### 3.3.6 前端

- Vue 3 + TypeScript + Vite + Pinia + Vue Router；Element Plus 负责表格、表单、弹窗；ECharts 负责图表。
- 由后端 OpenAPI 生成 TS 类型与 API client，减少契约漂移。
- 前端只做展示与交互，不做权限判断的最终依据；隐藏按钮不等于授权。
- SSE 优先，浏览器不支持或网络受限时退化为 1–2 秒轮询。

#### 3.3.7 模型网关

- 统一 `ChatModelAdapter` 接口：`chat(purpose, payload, budget) -> ModelResponse`。
- 第一版优先支持 OpenAI-compatible `POST /v1/chat/completions`；供应商差异放在适配器，不污染业务代码。
- 每个用途（理解、SQL 生成、SQL 复核、回答总结）独立路由、独立主备、独立超时与预算。
- 模型连通性测试由 worker 的网关执行，API 只受理并返回测试任务/状态，避免 API 进程直接出网。
- 密钥使用 AES-256-GCM 加密，主密钥来自部署环境/密钥文件，不与密文同表；后台只显示掩码。

#### 3.3.8 文件与快照

- 第一版使用本地受控卷 `/data/chatbi/{snapshots,exports,tmp}`；文件权限 `0600`，目录 `0700`。
- 文件逻辑 ID 与物理路径分离，数据库存相对键；下载必须经 API 鉴权，不暴露静态目录。
- 容量增长或多节点时，替换为 S3 兼容对象存储；接口保持不变。

#### 3.3.9 可观测性

- 应用输出 JSON 行日志到 stdout，由容器日志驱动收集；字段固定：`ts, level, service, trace_id, task_id, user_id_hash, event, latency_ms, error_code`。
- Prometheus 指标通过 `/metrics` 暴露（仅内网），包括任务、模型、SQL、队列、连接池、权限拒绝、导出。
- 告警先落 `alert_event` 表并由通知适配器发送；渠道属 DEC-18，不预设邮件/短信。

#### 3.3.10 部署

- Docker Compose 编排 `nginx`、`api`、`worker`、`beat`、`mysql`、`redis`；业务 MySQL 为外部既有实例。
- 仅 `nginx` 暴露 443；`api`、`worker`、`mysql`、`redis` 只在内部网络。
- 镜像使用非 root 用户、只读根文件系统（可写卷单独挂载）、健康检查与资源限制。

### 3.4 版本基线（建议，评审时锁定精确版本）

| 组件 | 建议版本 | 约束 | 验证要求 |
| --- | --- | --- | --- |
| Python | 3.12.x | 与依赖 wheel 兼容 | 锁定 `requirements.lock`/`uv.lock` |
| FastAPI | ≥0.115 | Pydantic v2 | 契约测试 |
| Pydantic | 2.x | 与 FastAPI 匹配 | 模型校验单测 |
| SQLAlchemy | 2.0.x | 异步/同步双驱动 | 迁移与流式读取测试 |
| Alembic | 1.13+ | 迁移可回滚 | 升级/降级演练 |
| sqlglot | 固定精确版本 | MySQL 方言行为随版本变化 | 解析/改写黄金用例 |
| Celery | 5.4.x | Redis broker | 崩溃/重复投递测试 |
| Redis | 7.2+ | 持久化策略需评估 | 重启恢复测试 |
| MySQL | 8.0.36+ | `SKIP LOCKED`、CTE、JSON | DBA 确认实际版本 |
| Nginx | 1.26+ | TLS 1.2/1.3 | 配置扫描 |
| Vue | 3.4+ | Composition API | 构建与 E2E |
| Vite | 5.x | Node 20+ 构建 | 锁文件 |
| Element Plus | 2.x | Vue 3 | 组件回归 |
| ECharts | 5.x | 图表配置 | 渲染快照 |

> 版本号只是评审起点，不是已批准依赖。sqlglot、Celery、MySQL 驱动升级必须跑完整 SQL 安全回归与取消测试。

---

## 4. 总体架构、进程/网络/数据边界

### 4.1 逻辑架构

```text
┌──────────────┐
│ 内网用户浏览器 │
└──────┬───────┘
       │ HTTPS（仅 443）
┌──────▼────────────────────────────────────────────────────────────┐
│ Nginx：TLS 终止、静态 SPA、反向代理、基础限流/超时                 │
└──────┬────────────────────────────────────────────────────────────┘
       │ /api/*
┌──────▼────────────────────────────────────────────────────────────┐
│ API 进程（FastAPI）                                                │
│  认证/会话 → 对象授权 → 参数校验 → 任务受理 → 状态/结果查询 → SSE   │
│  读写：应用 MySQL、Redis（会话/限流/缓存）                          │
└──────┬───────────────────────────────┬────────────────────────────┘
       │ Outbox 投递                    │ 读/写
┌──────▼──────────────┐        ┌───────▼────────────────────────────┐
│ Redis（broker）      │        │ 应用 MySQL 8.0                     │
│ 会话、限流、缓存、锁  │        │ 用户/权限/语义/任务/历史/审计/配置   │
└──────┬──────────────┘        └───────┬────────────────────────────┘
       │ Celery 消息                    │ 权威状态
┌──────▼────────────────────────────────────────────────────────────┐
│ Worker 进程（Celery）                                              │
│  任务领取 → 上下文/权限装载 → 模型网关 → SQL Gate → 业务库执行      │
│  → 结果规范化/脱敏/摘要 → 快照/文件 → 状态迁移 → 审计               │
└──────┬───────────────────────┬───────────────────────┬────────────┘
       │ 只读 SQL               │ HTTPS（最小化数据）    │ 文件读写
┌──────▼──────────────┐ ┌──────▼──────────────┐ ┌──────▼────────────┐
│ 生产 MySQL（外部）    │ │ 云端模型供应商        │ │ /data 受控卷        │
│ 最小权限只读账号      │ │ 主/备，按用途路由     │ │ 快照、导出、临时文件 │
└─────────────────────┘ └─────────────────────┘ └───────────────────┘
```

### 4.2 运行时进程与容器

| 容器/进程 | 职责 | 建议副本 | 关键约束 |
| --- | --- | --- | --- |
| `nginx` | TLS、静态资源、反向代理、请求体大小限制 | 1 | 仅暴露 443；HSTS（内网证书策略待定） |
| `api` | HTTP/SSE、认证、授权、任务受理、查询状态 | 2（可水平扩） | 无状态；会话在 Redis；不执行长 SQL |
| `worker` | Celery 消费、模型调用、SQL 执行、结果处理、导出 | 1–2 | 每任务独立业务库连接；并发可配 |
| `beat` | 定时触发元数据同步、清理、对账 | 1 | 只投递触发器，不直接执行 |
| `mysql` | 应用数据 | 1（单机） | 独立卷、备份、慢查询日志 |
| `redis` | 会话、限流、缓存、broker | 1（单机） | 需评估 AOF/RDB；不作为权威状态 |
| 业务 MySQL | 既有生产库 | 外部 | 只读账号；网络白名单；不纳入 Compose |

**进程边界原则**：API 不持有业务库长连接；worker 不处理 HTTP；所有业务库访问只发生在 worker 的 `SqlExecutor` 内；所有模型访问只发生在 `ModelGateway` 内。

### 4.3 信任边界

| 区域 | 组件 | 信任级别 | 主要控制 |
| --- | --- | --- | --- |
| 用户区 | 浏览器、网络 | 不可信 | TLS、认证、CSRF、CSP、输入校验、输出编码 |
| 边缘区 | Nginx | 受控但非授权中心 | TLS 终止、请求体限制、超时、基础限流、访问日志脱敏 |
| 应用区 | API、worker、beat | 受控 | 最小权限、服务间无隐式信任、参数化、审计 |
| 数据区 | 应用 MySQL、Redis、`/data` | 高敏感 | 网络隔离、凭据分离、加密卷（如可用）、备份加密 |
| 外部模型 | 供应商 API | 不可信 | 数据最小化、Endpoint 白名单、超时、响应校验、不执行模型建议 |
| 业务库 | 生产 MySQL | 高敏感、只读 | 最小权限账号、只读事务、超时、行数上限、DBA 放行 |

### 4.4 数据分类与流向

| 数据类别 | 示例 | 存储位置 | 是否允许出网 | 备注 |
| --- | --- | --- | --- | --- |
| 身份与凭据 | 用户名、密码哈希、会话 ID | 应用 MySQL、Redis | 否 | 密码只存 Argon2id 哈希；会话 ID 不落日志 |
| 权限配置 | 角色、模板、例外、行映射 | 应用 MySQL | 否 | 变更全审计 |
| 业务元数据 | 表名、字段、注释、外键 | 应用 MySQL | 仅最小必要 Schema | 注释需清洗秘密 |
| 用户问题 | 自然语言问题 | 应用 MySQL | 是（必要） | 先做凭据/PII 检查 |
| 候选 SQL | 模型生成 SQL | 应用 MySQL（审计） | 是（必要片段） | 普通用户不可见 |
| 查询结果 | 行、列、汇总 | 应用 MySQL 快照/`/data` | 默认否 | 仅最小摘要可出网 |
| 回答摘要 | 文本、图表配置 | 应用 MySQL | 是（授权摘要） | 需过小样本/字段规则 |
| 模型密钥 | API Key | 应用 MySQL 密文 | 否 | 主密钥独立托管 |
| 审计日志 | 事件、状态、耗时 | 应用 MySQL | 否 | 不含明文敏感值 |

### 4.5 关键架构不变量

1. 浏览器永不直连业务 MySQL、Redis、`/data` 或模型供应商。
2. 模型永不参与认证、授权、行范围生成或最终安全批准。
3. 所有业务 SQL 必须经过唯一 `SqlGate`；不存在旁路执行入口。
4. 任务状态以应用 MySQL 为唯一权威；Celery/Redis 丢失消息不得导致状态错误。
5. 权限在受理、执行前、发布前、共享打开、下载前五个检查点复核。
6. 原始明细默认不出内网；摘要也必须是“允许外发的摘要”，不是“截断后的明细”。
7. 密钥只能“写入/替换”，不能回读明文；日志、异常、备份清单不含明文。
8. 快照共享必须有范围证明；证明不足时只能降级为“接收者重查”。

---

## 5. 逻辑模块与建议工程结构

### 5.1 模块清单

| 模块 | 职责 | 对外接口 | 不负责 |
| --- | --- | --- | --- |
| `auth` | 登录、登出、会话、CSRF、密码哈希、登录审计 | `/api/auth/*`、`/api/me` | 业务权限判断 |
| `permission` | 角色模板、用户例外、有效权限合成、权限纪元、行范围映射 | 内部 `PermissionService` | 业务数据查询 |
| `identity` | 用户、部门、角色、业务身份映射 | `/api/admin/users` 等 | 认证凭据校验 |
| `metadata` | 结构采集、差异、版本、导入预览 | `/api/admin/metadata/*` | 业务语义解释 |
| `semantic` | 术语、指标、主题、关联、检索、发布 | `/api/admin/terms`、`/api/admin/metrics`、`/api/admin/topics` | SQL 执行 |
| `conversation` | 会话、消息窗口、结构化条件、成功基准 | `/api/conversations/*` | 任务调度 |
| `task` | 任务状态机、Outbox、租约、预算、取消 | 内部 + `/api/queries/*` | 模型或 SQL 细节 |
| `model_gateway` | 用途路由、主备、熔断、密钥、外发最小化 | 内部 `ModelGateway` | 权限与 SQL 批准 |
| `sqlgate` | SQP 编译、AST 解析、白名单、行谓词、复验 | 内部 `SqlGate` | 数据库连接 |
| `executor` | 只读连接、流式读取、超时、KILL、连接隔离 | 内部 `SqlExecutor` | 结果脱敏 |
| `result` | 规范化、脱敏、摘要、图表配置、截断标记 | 内部 `ResultService` | 历史持久化 |
| `history` | 历史记录、重查、删除、快照血缘 | `/api/history/*` | 共享授权 |
| `sharing` | 指定用户共享、范围证明、撤销 | `/api/shares/*` | 业务数据权限 |
| `export` | Excel 生成、文件生命周期、下载鉴权 | `/api/exports/*` | 查询执行 |
| `audit` | 查询审计、管理审计、告警事件 | 内部 + `/api/admin/audits` | 业务结果 |
| `admin` | 用户/权限/模型/资源/监控配置页面 API | `/api/admin/*` | 普通问数 |
| `common` | 配置、日志、追踪、错误、时钟、ID 生成 | 内部 | 业务规则 |

### 5.2 建议目录结构

```text
chatbi/
├── pyproject.toml
├── alembic.ini
├── migrations/
│   └── versions/
├── src/chatbi/
│   ├── main.py                 # FastAPI 应用工厂
│   ├── config.py               # 环境变量与启动校验
│   ├── api/
│   │   ├── deps.py             # 会话、权限、trace 依赖
│   │   ├── auth.py
│   │   ├── me.py
│   │   ├── conversations.py
│   │   ├── queries.py          # 提交、状态、SSE、结果、取消
│   │   ├── history.py
│   │   ├── shares.py
│   │   ├── exports.py
│   │   └── admin/
│   │       ├── users.py
│   │       ├── permissions.py
│   │       ├── metadata.py
│   │       ├── semantics.py
│   │       ├── models.py
│   │       ├── audits.py
│   │       └── metrics_view.py
│   ├── domain/
│   │   ├── auth/
│   │   ├── permission/
│   │   ├── metadata/
│   │   ├── semantic/
│   │   ├── conversation/
│   │   ├── task/
│   │   ├── sqlgate/
│   │   ├── result/
│   │   ├── history/
│   │   ├── sharing/
│   │   └── export/
│   ├── infrastructure/
│   │   ├── db/                 # SQLAlchemy 模型、仓储
│   │   ├── redis/              # 会话、限流、锁
│   │   ├── models/             # 供应商适配器
│   │   ├── files/              # 快照/导出卷
│   │   └── observability/      # 日志、指标、追踪
│   ├── workers/
│   │   ├── celery_app.py
│   │   ├── run_query.py
│   │   ├── export_query.py
│   │   ├── metadata_sync.py
│   │   └── maintenance.py
│   └── shared/
│       ├── errors.py
│       ├── ids.py
│       └── time.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   └── e2e/
└── web/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── api/                # OpenAPI 生成
        ├── stores/
        ├── views/
        ├── components/
        └── router/
```

### 5.3 依赖规则

1. `api` 只依赖 `domain` 的用例接口与 `infrastructure` 的只读适配；不得直接写 SQL 访问业务库。
2. `workers` 调用同一 `domain` 用例；不得复制一套业务规则。
3. `domain` 不依赖 FastAPI、Celery、SQLAlchemy 的具体实现；通过端口接口访问外部。
4. `infrastructure` 实现端口；供应商 SDK、数据库驱动、文件系统只出现在这一层。
5. `sqlgate` 不依赖 `executor`；它只接收 AST/SQP 并返回可执行 SQL 或拒绝码，便于单测与黄金用例。
6. 跨模块只通过显式服务接口或领域事件；禁止跨模块直接读对方表。

### 5.4 后台管理页面与模块映射

| 页面 | 主要模块 | 关键校验 |
| --- | --- | --- |
| 用户/部门/角色 | `identity`、`permission` | 引用检查、权限纪元递增 |
| 权限模板/例外 | `permission` | 例外子集校验、冲突拒绝 |
| 字段用途/敏感策略 | `permission`、`result` | 脱敏预览、云端发送开关 |
| 元数据同步/导入 | `metadata` | 防重入、预览版本一致性 |
| 术语/指标/主题 | `semantic` | 依赖存在、发布审核、失效阻断 |
| 模型管理 | `model_gateway` | Endpoint 白名单、密钥掩码、连通测试 |
| 审计/监控 | `audit`、`observability` | 审计读取授权、字段脱敏 |

### 5.5 前端路由与页面

| 路由 | 页面 | 主要能力 | 服务端授权 |
| --- | --- | --- | --- |
| `/login` | 登录 | 登录、错误提示 | 无 |
| `/chat/:conversationId?` | 问数工作台 | 主题、输入、消息、条件摘要、任务状态、结果卡片 | 会话归属 + 查询权 |
| `/history` | 个人历史 | 列表、筛选、删除、重查 | 本人 |
| `/history/:id` | 历史详情 | 问题、回答、条件、摘要、共享 | 本人 + 当前数据权限 |
| `/shares` | 我的共享 | 发出/收到、模式、撤销 | 分享者/接收者 |
| `/admin/users` | 用户/部门/角色 | 账号、归属、状态 | 用户管理权 |
| `/admin/permissions` | 权限与敏感策略 | 模板、例外、字段用途、掩码 | 权限管理权 |
| `/admin/metadata` | 元数据 | 同步、差异、导入预览 | 元数据管理权 |
| `/admin/semantics` | 语义 | 术语、指标、主题、审核 | 语义管理权 |
| `/admin/models` | 模型 | 用途、主备、密钥、测试 | 模型管理权 |
| `/admin/audits` | 审计 | 查询/管理事件 | 审计权 |
| `/admin/metrics` | 监控 | 指标、告警、队列 | 运维/审计权 |

前端路由守卫只用于体验；每个接口仍按 §6.9 检查点独立授权。

---

## 6. 身份认证、会话与有效权限模型

### 6.1 登录与会话建立

```text
浏览器 → POST /api/auth/login（用户名、密码、CSRF 初始化）
API → 校验参数与登录限流 → 查询用户（含状态、部门、角色）
    → Argon2id 校验 → 失败则统一提示并审计
    → 生成 256-bit session_id → Redis 写入会话（TTL）
    → Set-Cookie: __Host-chatbi_session=...; HttpOnly; Secure; SameSite=Lax
    → 返回 me（用户、部门、角色、可见功能、csrf_token）
```

- 登录失败不区分“用户不存在/密码错误/账号禁用”，统一 `AUTH_FAILED`，仅审计记录真实原因。
- 会话绝对上限建议 12 小时，空闲上限 30 分钟；具体值属 DEC-01，配置化。
- 登出删除 Redis 会话；管理员禁用用户时删除该用户全部会话（按 `user_id` 索引或会话集）。
- 不在浏览器保存长期 JWT；不使用 `localStorage` 存会话。

### 6.2 会话存储

Redis 键：`sess:{session_id}`，值为 JSON：

```json
{
  "user_id": "usr_01J...",
  "perm_epoch": 1842,
  "created_at": "2026-10-22T09:00:00Z",
  "last_seen_at": "2026-10-22T09:20:00Z",
  "ip_hash": "sha256:...",
  "ua_hash": "sha256:...",
  "csrf_secret": "base64url..."
}
```

- `ip_hash`/`ua_hash` 只用于异常检测，不作为强绑定；代理场景需正确解析 `X-Forwarded-For` 并只信任 Nginx。
- 每次请求校验会话存在、未过期、用户状态有效；`perm_epoch` 与当前纪元不一致时重新加载权限并更新会话。
- 会话 ID 不写普通日志；审计只记录 `session_id_hash` 前 12 位。

### 6.3 用户、部门、角色

| 实体 | 关键字段 | 规则 |
| --- | --- | --- |
| `app_user` | `id, login_name, display_name, password_hash, department_id, status, business_user_id, business_dept_ids` | 登录名唯一；禁用即拒绝新请求 |
| `department` | `id, name, parent_id, business_dept_id, status` | 第一版不自动包含下级部门；部门树仅用于展示 |
| `app_role` | `id, name, status` | 角色是模板容器，不直接等于数据权限 |
| `app_user_role` | `user_id, role_id` | 第一版通常单角色；多角色按并集，待 DEC-02 |
| `app_user`（业务身份） | `business_user_id, business_dept_ids` | 业务身份字段必须由管理员配置并校验 |

- `business_user_id` 是业务表中“本人”字段的取值，不是登录名；映射缺失时允许登录管理个人信息，但禁止查询相关数据。
- `business_dept_ids` 允许一人多部门（若业务如此），但第一版界面按单部门简化；范围组合见 DEC-04。

### 6.4 权限模型

权限授予的最小单元是 `(resource_type, resource_id, action)`：

| 资源类型 | 资源 ID 示例 | 说明 |
| --- | --- | --- |
| `MODULE` | `mod_finance` | 模块级入口与表集合 |
| `TABLE` | `tbl_expense` | 表级可查询性 |
| `COLUMN` | `col_amount` | 字段级用途 |
| `TOPIC` | `topic_reimburse` | 已发布主题可见性 |
| `METRIC` | `metric_reimburse_amount` | 指标可用性 |

动作集合（下表位值用于运行时快速聚合；数据库按“每行一个动作”存储，见 §15.3 的 `template_grant.action`）：

| 位 | 动作 | 含义 |
| --- | --- | --- |
| 1 | `VIEW_METADATA` | 可见表/字段的业务名称与说明 |
| 2 | `QUERY_SELECT` | 可在 SELECT 中引用 |
| 4 | `FILTER` | 可用于 WHERE/HAVING 条件 |
| 8 | `GROUP` | 可用于 GROUP BY |
| 16 | `SORT` | 可用于 ORDER BY |
| 32 | `JOIN` | 可作为连接键/连接表 |
| 64 | `EXPORT` | 可进入导出 |
| 128 | `VIEW_RAW` | 可查看/导出原值（否则仅掩码） |
| 256 | `CLOUD_SEND` | 字段可进入云端摘要/提示词 |
| 512 | `AGGREGATE_SMALL` | 允许小样本聚合（需配合阈值） |

`template_grant` 与 `user_exception` 都使用同一结构；`effect` 为 `ALLOW`/`DENY`。任何权限变更在同一事务内递增 `permission_epoch.epoch`。

### 6.5 有效权限合成

```text
effective(user, epoch):
    result = {}                      # key=(resource_type, resource_id, action)
    # 1. 角色模板并集
    for role in user.active_roles:
        for grant in template_grants(role):
            apply(result, grant)
    # 2. 用户例外（默认仅允许收缩）
    for ex in user.exceptions(active=True):
        if ex.effect == ALLOW and policy == SHRINK_ONLY:
            require_subset(ex, role_grants)   # 保存时已校验，此处防御性复核
        apply(result, ex)
    # 3. DENY 永远优先
    return result

apply(result, grant):
    key = (grant.resource_type, grant.resource_id, grant.action)
    if grant.effect == DENY:
        result[key] = False
    elif result.get(key) is not False:
        result[key] = True
```

- 默认 `exception_policy = SHRINK_ONLY`（TC-06 / DEC-03 未关闭前的保守值）：用户例外只能撤销模板权限，不能新增。
- 若业务最终要求“用户例外可扩大”，必须改为 `EXTEND_WITH_APPROVAL`，并增加审批、双人复核与审计；不得直接改默认值。
- 多角色按并集；任一角色 DENY 即拒绝；冲突不静默。
- 管理权（用户/权限/模型配置）与业务数据权分离；系统管理员不自动获得业务表查询权。

### 6.6 行级固定范围

`identity_scope_mapping` 按表配置：

| 字段 | 说明 |
| --- | --- |
| `table_id` | 语义表 ID |
| `scope_mode` | `PUBLIC`、`SELF`、`DEPT`、`SELF_OR_DEPT`、`DENY` |
| `user_column_id` | 本人字段；`SELF`/`SELF_OR_DEPT` 必填 |
| `dept_column_id` | 部门字段；`DEPT`/`SELF_OR_DEPT` 必填 |
| `join_path_json` | 间接范围路径；为空表示本表直连 |
| `status` | `ACTIVE`/`DISABLED` |

范围谓词：

```text
PUBLIC      -> 无包装
SELF        -> t.user_col = :business_user_id
DEPT        -> t.dept_col IN (:business_dept_ids)
SELF_OR_DEPT-> (t.user_col = :business_user_id OR t.dept_col IN (:business_dept_ids))
DENY        -> 拒绝查询
```

- 无映射、映射禁用、字段不存在、`business_user_id` 缺失：一律拒绝，不自动放行。
- 公共字典表必须显式标 `PUBLIC` 并说明理由；不能因为“看起来不敏感”默认全员可见。
- “本人及所属部门”的并集/交集/按表选择仍属 DEC-04；本文实现为可配置谓词，不替业务定案。
- 下级部门是否纳入、跨部门历史记录是否可见，均属 DEC-04；默认不展开。

### 6.7 敏感字段策略

`sensitive_field_policy` 按字段配置：

| 字段 | 说明 |
| --- | --- |
| `column_id` | 字段 ID |
| `classification` | `PII`、`FINANCE`、`CREDENTIAL`、`INTERNAL`、`PUBLIC` |
| `mask_type` | `NONE`、`PARTIAL`、`HASH`、`BUCKET`、`DENY` |
| `mask_pattern` | 如手机号 `138****1234`、邮箱 `a***@b.com` |
| `allowed_purposes` | 位掩码；覆盖查询/过滤/分组/排序/导出/云端 |
| `min_group_size` | 聚合最小样本数；低于阈值拒绝或合并 |
| `cloud_send` | 是否允许进入云端摘要；默认否 |

执行顺序：**先应用字段用途与行范围，再脱敏，再摘要/图表，再导出**。前端隐藏列不构成脱敏。

### 6.8 权限纪元与缓存

- `permission_epoch` 单行表：`id=1, epoch BIGINT, updated_at`。
- 任何用户/角色/模板/例外/映射/敏感策略变更，在同一事务内 `UPDATE permission_epoch SET epoch=epoch+1`。
- Redis 缓存：`perm:{user_id}:{epoch}`，TTL 5 分钟；未命中回源应用库并回填。
- 会话中的 `perm_epoch` 只用于检测变化；真正授权以回源后的有效权限为准。
- 缓存键必须含 `epoch`；禁止使用不含纪元的旧键。
- 权限变更后，运行中的任务在下一个检查点发现纪元变化，重新装载权限；若权限收缩导致计划不再合法，任务转为 `REJECTED` 或 `NEEDS_CLARIFICATION`，不按旧权限交付。

### 6.9 权限检查点

| 检查点 | 时机 | 校验内容 | 失败行为 |
| --- | --- | --- | --- |
| CP-1 | 请求受理 | 会话、用户状态、查询权、对象归属、限流 | 401/403/429，不创建任务 |
| CP-2 | SQL 执行前 | 重新装载有效权限、语义版本、表/字段/行范围 | 拒绝或澄清，不执行 |
| CP-3 | 结果发布前 | 权限纪元、字段用途、脱敏、摘要安全 | 丢弃结果或降级为表格 |
| CP-4 | 历史/共享打开 | 所有权/共享资格 + 当前数据权限 | 404/403，不泄露对象存在性 |
| CP-5 | 导出生成/下载 | 分别校验导出权、字段原值权、文件状态 | 拒绝生成/拒绝下载 |

### 6.10 本节待决策

- DEC-01：密码复杂度、锁定、首次修改、重置、会话时限。
- DEC-02：管理/权限/审计职责是否分离；多角色与部门层级。
- DEC-03：用户例外是否可扩大模板；多角色冲突优先级。
- DEC-04：本人/部门字段映射、范围组合、公共表分类。
- DEC-06：敏感清单、掩码类型、字段用途粒度、越权部分拒绝还是整次拒绝。

---

## 7. 元数据、业务语义与动态 Schema 检索

### 7.1 结构采集

采集使用独立只读连接，只读 `information_schema`，不执行 `COUNT(*)`、`MIN`、`MAX` 或数据抽样。

第一版 `data_source` 只允许一条 `ACTIVE` 记录；连接信息引用密钥，不存明文；多数据源、跨库查询属非目标（§2.3）。

```sql
-- 表
SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION, TABLE_COMMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;

-- 字段
SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_DEFAULT, IS_NULLABLE,
       DATA_TYPE, COLUMN_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION,
       NUMERIC_SCALE, COLUMN_KEY, EXTRA, COLUMN_COMMENT, GENERATION_EXPRESSION
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- 索引
SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, CARDINALITY, INDEX_TYPE
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;

-- 外键
SELECT k.TABLE_NAME, k.COLUMN_NAME, k.CONSTRAINT_NAME,
       k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME,
       r.DELETE_RULE, r.UPDATE_RULE
FROM information_schema.KEY_COLUMN_USAGE k
JOIN information_schema.REFERENTIAL_CONSTRAINTS r
  ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA
 AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME
WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME IS NOT NULL;
```

采集结果规范化：表/字段/索引/外键分别计算稳定哈希；与上一有效版本比较，生成 `added/removed/type_changed/comment_changed/relation_changed` 差异。

### 7.2 版本与发布

| 版本状态 | 含义 | 是否可用于查询 |
| --- | --- | --- |
| `DRAFT` | 采集后待审核 | 否 |
| `PUBLISHED` | 管理员确认，供检索与执行 | 是 |
| `STALE` | 上游结构变化，依赖未修复 | 否 |
| `ARCHIVED` | 历史版本，仅供追溯 | 否 |

- 发布是原子操作：新版本 `PUBLISHED` 与旧版本 `ARCHIVED` 在同一事务完成。
- 采集失败、部分表读取失败、差异无法计算：保留旧版本，不发布半套结构。
- 结构删除/重命名：相关术语、指标、主题、权限映射标记 `STALE`；相关查询拒绝并提示管理员。
- 业务说明（别名、解释、指标口径）与物理结构分表存储；同步不覆盖业务说明。

### 7.3 业务语义对象

| 对象 | 关键内容 | 发布规则 |
| --- | --- | --- |
| `sem_table` | 物理表、模块、主题、业务名、说明 | 随版本发布 |
| `sem_column` | 物理字段、业务名、同义词、单位、敏感分类 | 随版本发布 |
| `sem_relation` | 外键两端、方向、基数、是否受控 | 只允许物理外键或管理员显式补充（DEC-17） |
| `sem_term` | 术语、同义词、目标表/字段/指标、模块 | 管理员审核后生效 |
| `sem_metric` | 业务名、表达式、粒度、单位、时间字段、过滤、依赖表、版本 | 审核后发布；表达式仍过 SQL Gate |
| `sem_topic` | 名称、模块、说明、示例问题、依赖指标 | 建议→待审核→发布→停用 |

指标表达式不是“管理员任意 SQL 后门”：它必须是受限表达式（聚合、四则、条件、时间函数），由同一 `SqlGate` 解析；不得包含子查询、系统表、文件函数或写操作。

### 7.4 动态 Schema 检索

第一版采用**结构化检索**，向量检索为可选增强，不作为基线依赖。

```text
输入：问题文本、用户可访问模块/表/字段、已发布主题
步骤：
1. 术语/同义词精确匹配（权重 3）
2. 表名/字段名/注释分词匹配（权重 1–2）
3. 主题先验（用户选中主题 +2；主题示例问题相似 +1）
4. 外键图扩展：命中表的一跳关联表（+1），最多两跳
5. 过滤：未授权表/字段、STALE 对象、DENY 范围
6. 截断：表 ≤ 8，字段 ≤ 80，关系路径 ≤ 12，token 预算 ≤ 6k
输出：候选表/字段/关系/指标/术语 + 检索分数 + 语义版本
```

- 检索结果只用于构造提示词与 SQP 校验，不直接执行。
- 记录检索候选与命中原因，供后台排障；普通用户不可见。
- 若问题需要未授权表/字段，返回“当前权限不足”或澄清，不暴露完整结构。
- 向量检索若启用，向量只存业务语义文本的嵌入，不存原始数据；仍需经过同一授权过滤。

### 7.5 提示词构造

系统提示词固定包含：

1. 角色与边界：只输出结构化计划或受控 SQL；不得假设权限；不得访问系统表。
2. 可用对象清单：稳定 ID、业务名、类型、单位、注释摘要、允许的动作。
3. 指标定义：仅当前问题相关且已发布。
4. 关系路径：只列已发布、已授权的外键路径。
5. 输出契约：JSON Schema（SQP）或 SQL 约束（单条 SELECT、必须带 LIMIT 占位）。
6. 安全规则：禁止 `SELECT *`、系统库、文件函数、锁、写操作、多语句。

提示词不包含：原始明细、其他用户问题、完整历史、密钥、内部表名以外的系统信息。

### 7.6 失效处理

- 执行前比对 `sem_version`：若与检索时不一致，重新校验表/字段/关系；不合法则 `METADATA_STALE`。
- 指标版本变化：若任务引用旧版本，按旧版本口径执行并标注，或要求用户确认新口径；不得静默切换。
- 主题停用：新请求不可见；运行中任务在下一个检查点拒绝。
- 外键删除：相关关系路径失效；依赖该路径的查询拒绝，不猜测替代路径。

### 7.7 批量导入与手工维护

**导入格式**（Excel/CSV 的最终支持范围属 DEC-16）：

| 列 | 必填 | 说明 |
| --- | --- | --- |
| `object_type` | 是 | `TABLE`、`COLUMN`、`TERM`、`METRIC`、`TOPIC` |
| `table_name` / `column_name` | 视类型 | 必须能在当前 `sem_version` 中解析到物理对象 |
| `business_name` | 是 | 业务名/中文别名 |
| `synonyms` | 否 | 分号分隔 |
| `description` | 否 | 业务解释；不得覆盖物理标识 |
| `metric_expression` | 指标必填 | 受限表达式；仍过 SQL Gate |
| `unit` / `grain` | 否 | 单位/粒度 |
| `status` | 否 | 默认 `DRAFT`，不得直接 `PUBLISHED` |

流程：

```text
上传临时文件 → 解析（编码/表头/行数）→ 逐行校验
→ 生成差异预览（新增/修改/冲突/未知对象）
→ 管理员确认 → 单事务应用 → 审计 → 报告
```

- 默认整批校验通过才应用；部分成功需显式选择（DEC-16），且必须报告失败行号与原因。
- 不允许导入虚构的表/字段；物理对象必须已存在于当前元数据版本。
- 手工维护单对象时同样走校验与审计；业务说明不能覆盖物理名/类型。
- 主题建议由规则（模块、外键、指标）生成草稿，可选模型辅助；草稿必须管理员审核后才能发布，模型建议不自动对用户可见。
- 导入/手工维护都递增语义版本或产生新的 `DRAFT`，不直接修改已发布版本。

---

## 8. 多轮结构化条件、固定窗口与成功基准

### 8.1 两层上下文

| 层 | 内容 | 生命周期 | 是否进入模型 |
| --- | --- | --- | --- |
| 消息窗口 | 最近 N 轮用户/助手文本 | 会话内滑动 | 是，截断后 |
| 结构化查询状态 | 指标、维度、过滤、时间、排序、限制、版本 | 独立持久化 | 以紧凑 JSON 注入 |
| 长期历史 | 全部历史记录 | 长期 | 否，除非用户显式重查 |

两层分离的目的：窗口淘汰不影响历史与当前条件；历史全量不进入提示词。

### 8.2 QueryContext 结构

```json
{
  "context_id": "ctx_01J...",
  "conversation_id": "conv_01J...",
  "based_on_query_id": "qry_01J...",
  "sem_version": 42,
  "conditions": {
    "metrics": [
      {"id": "metric_reimburse_amount", "version": 3}
    ],
    "dimensions": [
      {"table_id": "tbl_expense", "column_id": "col_dept", "alias": "部门"}
    ],
    "filters": [
      {"table_id": "tbl_expense", "column_id": "col_status", "op": "eq", "value": "APPROVED"}
    ],
    "time_range": {
      "table_id": "tbl_expense",
      "column_id": "col_date",
      "start": "2026-07-01",
      "end": "2026-09-30",
      "grain": "quarter",
      "source": "explicit"
    },
    "order_by": [
      {"table_id": "tbl_expense", "column_id": "col_amount", "direction": "desc"}
    ],
    "limit": 200
  },
  "display": {"chart_hint": "auto"},
  "status": "DRAFT",
  "version": 7,
  "created_at": "2026-10-22T09:00:00Z"
}
```

约束：

- 只允许语义层中已发布、当前用户可用的指标/表/字段 ID；不接受模型自造名称。
- 权限谓词不在 `conditions` 中；它由服务端在执行前生成，模型不可见、不可改。
- `limit` 受服务端上限约束；模型给的值只能缩小，不能放大。
- 时间范围必须带 `source`（explicit/relative/inherited），便于重查时提示变化。

### 8.3 条件补丁语义

补丁操作：

| 操作 | 语义 | 示例 |
| --- | --- | --- |
| `set` | 新增或替换指定路径 | “只看已完成” → 新增 status 过滤 |
| `remove` | 删除指定用户条件 | “取消状态筛选” |
| `replace_time` | 替换时间范围，不叠加 | “不是上季度，是本季度” |
| `replace_metric` | 替换指标，保留兼容维度 | “换成客户数” |
| `append_dimension` | 增加分组 | “再按员工分组” |

规则：

1. 只允许修改 `conditions` 下的白名单路径；`sem_version`、`based_on_query_id`、权限相关字段不可由模型写。
2. 补丁必须产生 `diff`：`{path, before, after, action}`，前端展示“变更摘要”。
3. 冲突补丁（同一路径 set 后又 remove）整批拒绝，要求澄清。
4. 新问题明显切换主题时，不强行继承旧条件；先澄清“新查询/继续当前查询”。
5. 权限范围不能通过补丁移除；试图移除时返回 `PERMISSION_DENIED` 并审计。

### 8.4 固定窗口

- 默认 N=6 个用户轮次，配置项 `CONVERSATION_WINDOW_TURNS`；轮次定义与 N 属 DEC-09。
- 单条消息最大 2,000 字符；超长截断并提示；不把截断内容静默送入模型。
- 窗口外消息不进入模型，也不删除历史；需要时由用户显式重查或引用历史。
- 结构化状态始终完整注入（在 token 预算内）；若状态过大，优先保留指标、时间、过滤，维度/排序可摘要。

### 8.5 成功基准与失败候选

| 状态 | 是否可作“上一轮结果” | 规则 |
| --- | --- | --- |
| `SUCCEEDED` | 是 | 最近一次成功版本成为基准 |
| `NEEDS_CLARIFICATION` | 否 | 候选条件单独保存，不覆盖基准 |
| `FAILED` / `TIMED_OUT` | 否 | 候选条件保留，用户明确修正时可参考并标注来源 |
| `CANCELLED` | 否 | 即使数据库刚完成，未交付结果也丢弃 |
| `REJECTED` | 否 | 不进入自动修正流程 |

“这些结果/刚才那个”解析顺序：当前会话最近 `SUCCEEDED` → 若不存在则澄清；不跨会话取数。

### 8.6 澄清协议

`NEEDS_CLARIFICATION` 返回：

```json
{
  "status": "NEEDS_CLARIFICATION",
  "clarification": {
    "field": "time_range",
    "question": "“上季度”指 2026 年第三季度，还是最近一个已结束季度？",
    "options": [
      {"id": "2026Q3", "label": "2026 年第三季度"},
      {"id": "last_closed", "label": "最近一个已结束季度"}
    ],
    "allow_free_text": true
  },
  "trace_id": "trc_..."
}
```

- 澄清前不生成 SQL、不占用业务库连接。
- 用户回答后形成新的 `QueryContext` 版本，重新走权限与检索。
- 同一问题连续两次无法澄清时，返回可操作的示例问法，不无限追问。

### 8.7 示例

| 用户表达 | 补丁 | 结果摘要 |
| --- | --- | --- |
| “统计本部门上季度报销金额” | 初始：metric、dept 范围、time | 指标=报销金额；范围=本部门；时间=2026Q3 |
| “再按员工分组” | `append_dimension(employee)` | 新增：按员工分组 |
| “不是上季度，是本季度” | `replace_time(2026Q4)` | 时间：2026Q3 → 2026Q4 |
| “只看已完成” | `set(filter.status=APPROVED)` | 新增：状态=已完成 |
| “取消状态筛选” | `remove(filter.status)` | 移除：状态筛选 |
| “看所有部门” | 拒绝 | 固定范围不可移除 |

---

## 9. 查询任务、worker、幂等与可靠调度

### 9.1 状态机

```text
ACCEPTED
  → QUEUED
  → DISPATCHED            （内部状态，用户仍见“排队中”）
  → UNDERSTANDING
  → RETRIEVING
  → GENERATING
  → VALIDATING
  → EXECUTING
  → PROCESSING
  → ANSWERING
  → SUCCEEDED

任一中间状态 → NEEDS_CLARIFICATION
任一中间状态 → REJECTED
任一中间状态 → FAILED
任一中间状态 → TIMED_OUT
任一中间状态 → CANCEL_REQUESTED → CANCELLED
```

| 迁移 | 守卫 | 副作用 |
| --- | --- | --- |
| `ACCEPTED→QUEUED` | 参数、权限、限流通过 | 创建任务/上下文/审计；写 Outbox |
| `QUEUED→DISPATCHED` | Outbox 已投递 | 记录 dispatch_id；不改变用户可见状态 |
| `DISPATCHED→UNDERSTANDING` | worker 领到租约 | 记录 worker_id、attempt_no |
| `UNDERSTANDING→RETRIEVING` | 条件可解析、无歧义 | 记录条件版本 |
| `RETRIEVING→GENERATING` | 检索到可用对象 | 记录 sem_version、候选 |
| `GENERATING→VALIDATING` | 模型返回候选 SQP/SQL | 记录模型调用与预算 |
| `VALIDATING→EXECUTING` | SqlGate 通过、CP-2 通过 | 绑定业务库连接、记录 connection_id |
| `EXECUTING→PROCESSING` | 查询完成、未取消 | 记录行数/字节/耗时 |
| `PROCESSING→ANSWERING` | 脱敏/摘要/图表完成 | 记录降级警告 |
| `ANSWERING→SUCCEEDED` | CP-3 通过、结果持久化 | 更新成功基准、历史、审计 |
| 任意→`CANCEL_REQUESTED` | 本人或授权运维 | 设置取消时间；发布控制消息 |
| 任意→`FAILED` | 预算耗尽/不可恢复 | 记录错误类别；不覆盖成功基准 |

状态迁移使用乐观锁：`UPDATE query_task SET status=?, version=version+1 WHERE id=? AND status=? AND version=?`；影响行数为 0 视为并发冲突，重读后决定。

### 9.2 核心任务表（字段摘要）

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `query_task` | `id, user_id, conversation_id, context_id, parent_task_id, status, stage, priority, budget_json, perm_epoch, sem_version, cancel_requested_at, lease_owner, lease_expires_at, attempt_count, max_attempts, next_run_at, error_code, trace_id, version` | 任务权威状态 |
| `query_attempt` | `id, task_id, attempt_no, stage, worker_id, status, model_calls, sql_hash, connection_id, physical_cancel, started_at, finished_at, error_code, detail_json` | 每次执行尝试 |
| `task_outbox` | `id, aggregate_type, aggregate_id, event_type, payload_json, status, available_at, sent_at` | 事务内待投递 |
| `task_dispatch` | `dispatch_id, task_id, queue, status, created_at, last_error` | Celery 消息绑定 |
| `idempotency_key` | `user_id, scope, key, request_hash, response_json, expires_at` | 重复提交 |

完整 DDL 见 §15。

### 9.3 任务领取

```sql
START TRANSACTION;

SELECT id
FROM query_task
WHERE status IN ('QUEUED', 'DISPATCHED')
  AND next_run_at <= NOW(3)
  AND (lease_expires_at IS NULL OR lease_expires_at < NOW(3))
ORDER BY priority DESC, created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;

UPDATE query_task
SET status = 'UNDERSTANDING',
    stage = 'UNDERSTANDING',
    lease_owner = :worker_id,
    lease_expires_at = DATE_ADD(NOW(3), INTERVAL 30 SECOND),
    attempt_count = attempt_count + 1,
    version = version + 1
WHERE id = :task_id;

COMMIT;
```

- 领取必须在一个短事务内完成；不在事务内调用模型或数据库。
- `SKIP LOCKED` 只解决“多个 worker 不抢同一行”，不保证 SQL 只执行一次；执行幂等由 attempt 与状态机保证。
- 领取失败（影响行数 0）直接返回，不重试同一消息；消息重复投递是正常事件。

### 9.4 租约、心跳与回收

- worker 每 5 秒 `UPDATE query_task SET lease_expires_at=NOW(3)+30s WHERE id=? AND lease_owner=?`。
- 心跳失败连续 3 次：worker 主动停止后续阶段，标记 `LEASE_LOST`，不再写结果。
- 回收器每 30 秒扫描 `lease_expires_at < NOW(3)` 的任务：
  - 阶段 ≤ `VALIDATING`：attempt 标记 `LOST`，任务回 `QUEUED`，`next_run_at=NOW()+退避`。
  - 阶段 = `EXECUTING`：标记 `EXECUTION_UNKNOWN`，任务转 `FAILED`（错误码 `DB_EXECUTION_UNKNOWN`），不自动重跑；提示用户重试或运维核对。
  - 阶段 ≥ `PROCESSING`：若中间结果已持久化，可重新入队处理；否则失败。
- 最大尝试次数默认 3；超过后 `FAILED`，保留 trace 与错误类别。

### 9.5 Celery 集成

```python
# 设计示例，不是可直接部署的配置
app.conf.update(
    broker_url="redis://redis:6379/0",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_default_queue="chatbi.query",
    task_routes={
        "chatbi.tasks.run_query": {"queue": "chatbi.query"},
        "chatbi.tasks.run_export": {"queue": "chatbi.export"},
        "chatbi.tasks.sync_metadata": {"queue": "chatbi.maintenance"},
    },
)
```

- 禁止 `autoretry_for` 与无限 `self.retry`；所有重试先写 DB 状态与预算，再由调度器重新投递。
- `run_query(task_id)` 只接收业务 ID；消息体不含问题、SQL、结果或密钥。
- 任务开始、结束都写 `query_attempt`；Celery 日志只用于排障，不作为审计。
- `beat` 只投递 `sync_metadata`、`cleanup`、`reconcile` 等触发器；触发器也写任务表，走同一状态机。

### 9.6 幂等

- 提交接口要求 `Idempotency-Key`；键作用域 `(user_id, endpoint, key)`；保存请求哈希与响应。
- 相同键 + 相同请求哈希：返回原响应（202/任务 ID），不创建新任务。
- 相同键 + 不同请求哈希：`409 IDEMPOTENCY_CONFLICT`。
- 键有效期默认 24 小时；过期清理；不用于跨用户。
- worker 侧幂等：`(task_id, attempt_no)` 唯一；重复消息若任务已终态，直接 no-op。

### 9.7 统一预算

预算在任务创建时写入，所有阶段共享，防止“重试 × 修正 × 主备”相乘：

```json
{
  "max_wall_ms": 60000,
  "max_model_calls": 6,
  "max_sql_fix": 2,
  "max_rows": 1000,
  "max_bytes": 8388608,
  "sql_timeout_ms": 10000,
  "max_retries": 3
}
```

- 每次模型调用/ SQL 尝试前原子扣减：`UPDATE query_task SET budget_used=... WHERE ... AND used+?<=limit`。
- 预算耗尽 → `TIMED_OUT`/`FAILED`，不再调用模型或数据库。
- 具体数值属 DEC-11；以上只是设计起点，不是承诺。

### 9.8 取消传播

```text
API: POST /api/queries/{id}/cancel
  → 校验所有权/运维权限
  → UPDATE query_task SET cancel_requested_at=NOW(3), status='CANCEL_REQUESTED', version=version+1
  → PUBLISH cancel:{task_id}（Redis pub/sub，仅通知）
  → 返回 202 + 当前状态

Worker:
  → 每个阶段边界检查 cancel_requested_at
  → 若正在 SQL：控制连接执行 KILL QUERY :connection_id
  → 记录 physical_cancel = CONFIRMED / FAILED / UNKNOWN
  → 关闭并隔离该连接；不归还池
  → 终态 CANCELLED；迟到结果按 version 丢弃
```

- `KILL QUERY` 只能作用于本任务绑定的 `connection_id`；不得按用户/模式模糊匹配。
- 若账号无 `PROCESS`/`CONNECTION_ADMIN` 且无法 KILL 他人连接，只允许 KILL 自己的连接；否则关闭 socket，标记物理状态未知。
- HTTP 断开不触发取消；只有显式取消或超时预算触发。
- 取消是幂等操作；已终态返回当前终态，不伪造新的取消成功。

### 9.9 崩溃恢复与对账

| 场景 | 处理 |
| --- | --- |
| API 重启 | 任务不受影响；SSE 客户端用 `Last-Event-ID` 重连；状态从 DB 读 |
| worker 崩溃（未执行 SQL） | 租约过期 → 回 `QUEUED` → 重新领取 |
| worker 崩溃（SQL 执行中） | `EXECUTION_UNKNOWN` → 不自动重跑；提示重试/运维核对 |
| Redis 丢失消息 | Outbox 扫描 `status=PENDING` 且 `available_at<=now` 重投；任务状态不变 |
| Celery 重复投递 | 任务已终态则 no-op；未终态则按租约竞争，只有一个 worker 领取 |
| 数据库主从切换（应用库） | 任务表以主库为准；切换后重新领取；不依赖 Redis 状态 |
| 业务库断连 | 确认旧执行结束且预算允许才有限重试；否则失败 |

对账任务每 5 分钟检查：`QUEUED` 超过 2 分钟未投递、`DISPATCHED` 超过 5 分钟未领取、租约过期、Outbox 积压、终态缺失审计。

### 9.10 并发与公平性

- 全局 worker 并发默认 4；交互查询队列优先于导出/维护。
- 单用户并发默认 1–2；超出返回 `RATE_LIMITED` 或排队。
- 导出使用独立队列与独立并发，避免大文件生成阻塞问数。
- 业务库连接池按 worker 进程独立配置；执行中的连接不归还池，直到查询结束或被隔离。
- 队列有界；过载时拒绝新任务，不无限堆积。

---

## 10. 受控 SQL、AST 校验与固定行权限

### 10.1 处理流水线

```text
输入 A：SQP JSON（计划优先）
   → 语义层校验 ID/版本/权限
   → SqpCompiler 用语义目录构造 AST
   → SqlGate

输入 B：候选 SQL（兜底）
   → sqlglot parse(read="mysql")
   → SqlGate

SqlGate：
  1. 单语句、根节点类型、禁用节点
  2. 结构白名单（深度/连接数/UNION 分支/函数）
  3. 作用域树与标识符解析
  4. 表/字段/动作授权
  5. 行范围包装（基表 → 派生表）
  6. 生成最终 SQL + 参数
  7. 重新 parse 并复验
  8. 成本/复杂度守卫
  9. 输出 ValidatedSql 或拒绝码
```

`SqlGate` 是纯函数式组件：输入 SQP/SQL、权限快照、语义版本、用户范围；输出 SQL 与参数，或结构化拒绝。它不连接数据库、不调用模型，便于单元测试与黄金用例回归。

### 10.2 SQP 契约

```json
{
  "type": "aggregate",
  "metric": {"id": "metric_reimburse_amount", "version": 3},
  "dimensions": [
    {"table_id": "tbl_expense", "column_id": "col_dept", "alias": "部门"}
  ],
  "filters": [
    {"table_id": "tbl_expense", "column_id": "col_status", "op": "eq", "value": "APPROVED"}
  ],
  "time_range": {
    "table_id": "tbl_expense",
    "column_id": "col_date",
    "start": "2026-07-01",
    "end": "2026-09-30",
    "grain": "quarter"
  },
  "order_by": [
    {"table_id": "tbl_expense", "column_id": "col_amount", "direction": "desc"}
  ],
  "limit": 200
}
```

| 字段 | 约束 |
| --- | --- |
| `type` | `aggregate`、`detail`、`comparison`；第一版只支持前三类 |
| `metric` | 必须是已发布指标；版本必须存在；表达式由服务端解析 |
| `dimensions` | 最多 6 个；必须是已授权、可分组字段 |
| `filters` | 最多 12 个；操作符白名单；值类型校验 |
| `time_range` | 必须绑定时间字段；相对时间由服务端解析为绝对区间 |
| `order_by` | 最多 3 个；必须出现在 SELECT 或聚合中 |
| `limit` | 1–1000；服务端上限，模型只能缩小 |

操作符白名单：`eq`、`neq`、`in`、`not_in`、`between`、`gt`、`gte`、`lt`、`lte`、`like_prefix`、`is_null`、`is_not_null`。不接受原始 SQL 片段、函数调用、子查询作为值。

### 10.3 sqlglot 解析约定

- 固定精确版本；升级必须跑完整黄金用例与安全回归。
- `sqlglot.parse(sql, read="mysql")`；返回多于 1 个表达式即拒绝。
- 不依赖 sqlglot 的 `qualify`/`optimizer` 作为权限判断；权限作用域由本项目显式实现，避免库版本行为差异。
- 解析前拒绝包含 `/*+` 优化器提示的 SQL；普通注释剥离后再解析。
- 生成 SQL 使用 `expression.sql(dialect="mysql")`；参数使用 `exp.Placeholder`，最终由自定义生成器按顺序输出 `%s` 与参数列表。
- 所有标识符来自语义目录（反引号转义），不拼接模型提供的表名/字段名。

### 10.4 结构白名单

**允许的根节点**：

- `exp.Select`
- `exp.Union` / `exp.UnionAll`（每个分支必须是 `Select`，分支数 ≤ 5）
- 带 `WITH` 的上述查询（非递归；递归 CTE 第一版拒绝）

**允许的子句/节点**：

- `FROM`、`JOIN`（INNER/LEFT；CROSS 仅显式且涉及 ≤ 2 表）、`WHERE`、`GROUP BY`、`HAVING`、`ORDER BY`、`LIMIT`
- 非递归 CTE、派生表（必须有别名）
- 聚合函数、标量函数（白名单）
- `CASE WHEN`、`COALESCE`、`NULLIF`、`CAST`（仅允许安全类型）

**拒绝的节点/语句**：

| 类别 | 示例 | 拒绝码 |
| --- | --- | --- |
| 写操作 | INSERT/UPDATE/DELETE/REPLACE | `SQL_STATEMENT_NOT_ALLOWED` |
| DDL | CREATE/ALTER/DROP/TRUNCATE/RENAME | `SQL_STATEMENT_NOT_ALLOWED` |
| 事务/锁 | BEGIN/COMMIT/ROLLBACK/SET/FOR UPDATE/LOCK IN SHARE MODE | `SQL_STATEMENT_NOT_ALLOWED` |
| 多语句 | `SELECT 1; SELECT 2` | `SQL_MULTIPLE_STATEMENTS` |
| 文件/外传 | `INTO OUTFILE`、`LOAD_FILE`、`LOAD DATA` | `SQL_FUNCTION_NOT_ALLOWED` |
| 危险函数 | `SLEEP`、`BENCHMARK`、`GET_LOCK`、`RELEASE_LOCK`、`MASTER_POS_WAIT` | `SQL_FUNCTION_NOT_ALLOWED` |
| 系统库 | `information_schema`、`mysql`、`performance_schema`、`sys` | `SQL_SYSTEM_SCHEMA` |
| 递归 CTE | `WITH RECURSIVE` | `SQL_UNSUPPORTED_SYNTAX` |
| 优化器提示 | `/*+ ... */` | `SQL_HINT_NOT_ALLOWED` |
| 存储过程/动态 SQL | `CALL`、`PREPARE`、`EXECUTE` | `SQL_STATEMENT_NOT_ALLOWED` |

**函数白名单（第一版建议）**：

- 聚合：`COUNT`、`SUM`、`AVG`、`MIN`、`MAX`、`COUNT(DISTINCT ...)`
- 数值：`ROUND`、`ABS`、`CEIL`、`FLOOR`、`TRUNCATE`
- 字符串：`CONCAT`、`LOWER`、`UPPER`、`TRIM`、`SUBSTRING`、`LEFT`、`RIGHT`
- 日期：`DATE`、`DATE_FORMAT`、`YEAR`、`MONTH`、`DAY`、`DATE_ADD`、`DATE_SUB`、`DATEDIFF`
- 空值：`COALESCE`、`NULLIF`
- 条件：`CASE`（表达式，不是函数）
- 转换：`CAST`（仅 `CHAR`、`DECIMAL`、`DATE`、`DATETIME`、`SIGNED`）

不在白名单的函数一律拒绝；新增函数需安全评审与黄金用例。

### 10.5 标识符解析与授权

对每个 `exp.Table`：

1. 若是 CTE 名称：解析到 CTE 定义，不当作物理表。
2. 若是派生表：递归校验其内部查询；要求别名。
3. 否则按 `catalog`（当前 `sem_version` 的 schema 快照）解析 `schema.table`；未指定 schema 时使用配置的业务库 schema。
4. 表不存在、未发布、`STALE`、未授权：`SQL_UNKNOWN_TABLE` / `SQL_TABLE_NOT_ALLOWED`。
5. 检查表级 `QUERY_SELECT`；连接表还需 `JOIN`。

对每个 `exp.Column`：

1. 解析限定符（表别名/表名）；无限定符时在作用域内查找唯一列；多表同名列且无限定 → `SQL_AMBIGUOUS_COLUMN`。
2. 映射到 `column_id`；未知列 → `SQL_UNKNOWN_COLUMN`。
3. 按所在子句检查动作：
   - `SELECT` / `GROUP BY` 表达式 → `QUERY_SELECT`（分组还需 `GROUP`）
   - `WHERE` / `HAVING` → `FILTER`
   - `ORDER BY` → `SORT`
   - `JOIN ... ON` → `JOIN`
4. 字段被 `DENY` 或用途位缺失 → `SQL_COLUMN_NOT_ALLOWED` / `SQL_ACTION_NOT_ALLOWED`。
5. 敏感字段无 `VIEW_RAW`：允许进入查询，但结果层强制掩码；不得进入导出原值。

`SELECT *` 处理：

- 展开为当前用户有 `QUERY_SELECT` 的列；无任何可用列 → 拒绝。
- 展开结果写入 `columns_used`，审计记录“由 * 展开”。
- `COUNT(*)` 不展开列，但仍检查表级权限。

### 10.6 行范围包装

**目标**：在连接、聚合、子查询、UNION 之前完成行过滤，避免“先聚合后过滤”导致泄露或口径错误。

**算法**：

```text
for each base table occurrence t in AST:
    mapping = scope_mapping(t.table_id, current_user)
    if mapping is None or mapping.status != ACTIVE:
        reject SQL_SCOPE_UNMAPPED
    if mapping.scope_mode == DENY:
        reject SQL_SCOPE_UNPROVABLE
    if mapping.scope_mode == PUBLIC:
        continue
    predicate = build_scope_predicate(t, mapping, user)
    t.replace_with(
        Subquery(
            Select(*).from_(t.copy()).where(predicate),
            alias=t.alias_or_name
        )
    )
```

`build_scope_predicate`：

```text
SELF:
  t.user_col = :business_user_id

DEPT:
  t.dept_col IN (:business_dept_ids)

SELF_OR_DEPT:
  (t.user_col = :business_user_id OR t.dept_col IN (:business_dept_ids))

间接路径（join_path_json 非空）:
  EXISTS (
    SELECT 1
    FROM path_table p
    WHERE p.target_col = t.fk_col
      AND p.scope_col IN (:business_dept_ids)   -- 或 = :business_user_id
  )
```

**为什么用派生表而不是直接往 WHERE 追加**：

| 场景 | 直接追加 WHERE | 派生表包装 |
| --- | --- | --- |
| INNER JOIN | 可行 | 可行 |
| LEFT JOIN | 会把外连接变成内连接，语义错误 | 先在右表过滤，再外连接，语义正确 |
| 聚合后再过滤 | 可能先聚合了越权行 | 聚合前已过滤 |
| 子查询/UNION | 注入位置难统一 | 每个基表统一包装 |
| 自连接 | 别名混淆 | 每个别名独立包装 |

**性能注意**：派生表可能阻止部分条件下推。MySQL 8 通常可合并派生表；执行前用 `EXPLAIN` 检查是否出现 `DERIVED` 且无法合并。若性能不可接受，优化顺序为：① 确认索引；② 对 INNER JOIN 场景改为 WHERE 注入（需证明语义等价）；③ 仍不达标则拒绝或要求 DBA 评估。不得为了性能取消行过滤。

**示例（LEFT JOIN）**：

```sql
-- 原始
SELECT d.name, SUM(e.amount)
FROM expense e
LEFT JOIN department d ON d.id = e.dept_id
GROUP BY d.name;

-- 包装后（示意）
SELECT d.name, SUM(e.amount)
FROM (
  SELECT * FROM expense
  WHERE (user_id = %s OR dept_id IN (%s, %s))
) AS e
LEFT JOIN (
  SELECT * FROM department
  WHERE (dept_id IN (%s, %s))
) AS d ON d.id = e.dept_id
GROUP BY d.name;
```

> 示例中的 `department` 是否应受行范围约束，取决于该表映射；公共字典表可标 `PUBLIC`。示例只说明包装位置，不表示业务表结构。

### 10.7 重写后复验

生成最终 SQL 后必须再次 parse 并执行：

1. 单语句、根节点类型、禁用节点检查。
2. 表/字段/动作授权检查（按最终 AST，不按中间结果）。
3. 每个基表 occurrence 必须有：`PUBLIC` 映射，或带范围谓词的派生表包装。
4. 参数数量、顺序、类型与 `params` 列表一致；占位符不得残留。
5. `LIMIT` 不超过服务端上限；`ORDER BY` 不引入未授权列。
6. 不允许通过 `/* ... */` 注释、字符串拼接、反引号逃逸绕过标识符检查。
7. 记录 `plan_hash = sha256(final_sql + params_schema + sem_version + perm_epoch)`。

复验失败 → `SQL_REWRITE_INVALID`，整次查询拒绝，不执行“接近正确”的 SQL。

### 10.8 成本与复杂度守卫

| 守卫 | 规则 | 动作 |
| --- | --- | --- |
| 连接数 | ≤ 8 个表 | 超出拒绝 |
| 子查询深度 | ≤ 3 | 超出拒绝 |
| UNION 分支 | ≤ 5 | 超出拒绝 |
| 笛卡尔积 | 无 ON/USING 的 JOIN | 拒绝（显式 CROSS JOIN ≤ 2 表另行评审） |
| 聚合嵌套 | 聚合内再聚合 | 拒绝 |
| `ORDER BY` + 无 `LIMIT` | 大结果排序 | 强制加服务端 `LIMIT` 或拒绝 |
| `EXPLAIN` 估算 | `query_cost` > 阈值 | 拒绝或要求缩小范围 |
| 扫描行数 | `rows_examined` 估算 > 阈值 | 拒绝或提示 |
| 结果行/字节 | 执行期上限 | 截断并标记 |

`EXPLAIN FORMAT=JSON` 只读、不执行查询，但复杂 SQL 的优化过程也可能耗时；必须设置超时并在独立连接执行。若 `query_cost` 不可用（版本差异），退回语法守卫 + `rows` 估算，并记录“成本证据不足”。

### 10.9 拒绝码

| 拒绝码 | 含义 | 用户提示 |
| --- | --- | --- |
| `SQL_PARSE_FAILED` | 无法解析 | 问题暂不支持，请调整表述 |
| `SQL_MULTIPLE_STATEMENTS` | 多条语句 | 仅支持单条查询 |
| `SQL_STATEMENT_NOT_ALLOWED` | 非 SELECT | 仅支持查询 |
| `SQL_UNSUPPORTED_SYNTAX` | 未支持语法 | 当前语法不支持 |
| `SQL_UNKNOWN_TABLE` | 表不存在/未发布 | 相关数据暂不可用 |
| `SQL_TABLE_NOT_ALLOWED` | 表未授权 | 当前权限不足 |
| `SQL_UNKNOWN_COLUMN` | 字段不存在 | 相关字段暂不可用 |
| `SQL_AMBIGUOUS_COLUMN` | 字段歧义 | 请补充限定 |
| `SQL_COLUMN_NOT_ALLOWED` | 字段未授权 | 当前权限不足 |
| `SQL_ACTION_NOT_ALLOWED` | 动作未授权 | 当前权限不足 |
| `SQL_FUNCTION_NOT_ALLOWED` | 函数不在白名单 | 当前写法不支持 |
| `SQL_SYSTEM_SCHEMA` | 访问系统库 | 当前写法不支持 |
| `SQL_SCOPE_UNMAPPED` | 行范围未配置 | 请联系管理员 |
| `SQL_SCOPE_UNPROVABLE` | 无法证明行范围 | 当前问题不支持 |
| `SQL_COST_EXCEEDED` | 成本超限 | 请缩小时间/范围 |
| `SQL_LIMIT_EXCEEDED` | 行数超限 | 请缩小范围 |
| `SQL_HINT_NOT_ALLOWED` | 优化器提示 | 当前写法不支持 |
| `SQL_REWRITE_INVALID` | 重写复验失败 | 内部安全拒绝 |

### 10.10 黄金用例（安全回归基线）

| 编号 | 输入 | 期望 |
| --- | --- | --- |
| SG-01 | `SELECT * FROM expense` | 展开授权列；无权限列不出现 |
| SG-02 | `SELECT * FROM expense e JOIN user u ON ...` | 两表均包装；字段逐列校验 |
| SG-03 | `SELECT ... FROM a LEFT JOIN b ...` | b 在连接前过滤；外连接语义保持 |
| SG-04 | `SELECT ... FROM (SELECT ... FROM expense) x` | 派生表内部基表包装 |
| SG-05 | `WITH x AS (SELECT ...) SELECT ...` | CTE 内部包装；非递归 |
| SG-06 | `SELECT ... UNION SELECT ...` | 每个分支独立包装 |
| SG-07 | 别名与表名混用 | 正确解析；歧义拒绝 |
| SG-08 | `SELECT information_schema.tables` | `SQL_SYSTEM_SCHEMA` |
| SG-09 | `SELECT SLEEP(10)` | `SQL_FUNCTION_NOT_ALLOWED` |
| SG-10 | `SELECT ... INTO OUTFILE` | `SQL_STATEMENT_NOT_ALLOWED` |
| SG-11 | `SELECT 1; DROP TABLE x` | `SQL_MULTIPLE_STATEMENTS` |
| SG-12 | `SELECT ... FOR UPDATE` | `SQL_STATEMENT_NOT_ALLOWED` |
| SG-13 | 未授权字段过滤 | `SQL_COLUMN_NOT_ALLOWED` |
| SG-14 | 未配置行范围表 | `SQL_SCOPE_UNMAPPED` |
| SG-15 | 自连接两次 | 两个别名独立包装 |
| SG-16 | `COUNT(*)` | 允许；表级权限检查 |
| SG-17 | 深层子查询 | `SQL_UNSUPPORTED_SYNTAX` |
| SG-18 | 笛卡尔积 | `SQL_COST_EXCEEDED` 或拒绝 |
| SG-19 | `/*+ INDEX(...) */` | `SQL_HINT_NOT_ALLOWED` |
| SG-20 | 重写后残留未包装表 | `SQL_REWRITE_INVALID` |

> 这些用例是**待实现、待运行**的回归清单，不表示已通过。每个用例需绑定固定 schema、权限快照与期望结果。

---

## 11. MySQL 执行、成本限制与取消

### 11.1 账号与连接

| 项目 | 要求 |
| --- | --- |
| 账号 | 独立 `chatbi_ro`；仅 `SELECT`；仅授权 schema/表；禁止 `FILE`、`PROCESS`（除非 DBA 批准取消方案） |
| 网络 | 仅 worker 所在网段可连；白名单；TLS（如环境支持） |
| 连接 | 每任务独立连接；不复用执行中的连接；连接池仅用于短查询 |
| 会话 | `SET SESSION TRANSACTION READ ONLY`；`SET SESSION MAX_EXECUTION_TIME`；`SET SESSION lock_wait_timeout` |
| 事务 | `START TRANSACTION READ ONLY` → 执行 → `COMMIT`/`ROLLBACK`；不做长事务 |
| 字符集 | `utf8mb4`；时区 UTC；`time_zone='+00:00'` |

### 11.2 执行参数（设计起点，非承诺）

| 参数 | 建议值 | 说明 |
| --- | --- | --- |
| 连接超时 | 3 s | 不含 DNS |
| 读超时 | 15 s | 驱动 socket |
| SQL 硬超时 | 10 s | `MAX_EXECUTION_TIME`，仅 SELECT |
| 锁等待 | 5 s | `lock_wait_timeout` |
| 结果行上限 | 1,000 | 超出截断并标记 |
| 结果字节上限 | 8 MB | 读取期累计 |
| 单任务总预算 | 60 s | 含模型与排队 |
| 连接池大小 | 5 + 5 overflow | 每 worker 进程 |

具体值属 DEC-11；DBA 必须按生产负载复核。

### 11.3 流式读取

```python
# 设计示例
with engine.connect() as conn:
    conn.exec_driver_sql("SET SESSION MAX_EXECUTION_TIME = %s", (sql_timeout_ms,))
    conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
    conn.exec_driver_sql("START TRANSACTION READ ONLY")
    result = conn.exec_driver_sql(validated.sql, validated.params)
    cursor = result.cursor
    while True:
        rows = cursor.fetchmany(500)
        if not rows:
            break
        for row in rows:
            size += estimate_bytes(row)
            if size > max_bytes:
                truncated = True
                break
            yield normalize(row)
        if truncated:
            break
    conn.exec_driver_sql("ROLLBACK")
```

- 禁止 `fetchall()`；禁止先读全量再截断。
- 读取过程中若取消标志置位，停止 fetch、关闭连接。
- 结果集列类型来自 cursor description；不信任 SQL 中的别名推断类型。

### 11.4 取消与物理停止

```text
1. 任务开始时：SELECT CONNECTION_ID() → 写入 query_attempt.connection_id
2. 取消请求：worker 用独立控制连接执行 KILL QUERY <connection_id>
3. 结果：
   - KILL 成功 → physical_cancel=CONFIRMED
   - KILL 报错/无权限 → 关闭业务连接 socket → physical_cancel=UNKNOWN
   - 查询已结束 → physical_cancel=NOT_APPLICABLE
4. 连接标记 QUARANTINED，不归还池；由清理任务关闭/丢弃
```

- 只允许 KILL 本任务绑定的连接；不得按用户、schema、SQL 文本模糊匹配。
- `KILL QUERY` 只停止语句，不终止连接；`KILL CONNECTION` 仅在连接泄漏且 DBA 批准时使用。
- HTTP 超时、浏览器关闭、SSE 断开都不自动触发 KILL；必须显式取消或任务预算超时。
- 取消确认时间、驱动能力、断线策略属 DEC-12。

### 11.5 错误映射

| MySQL 错误 | 分类 | 用户码 | 处理 |
| --- | --- | --- | --- |
| 1064 | 语法 | `SQL_PARSE_FAILED` | 可有限修正，但每次全校验 |
| 1142 | 权限 | `DB_PERMISSION_DENIED` | 拒绝；检查账号/授权配置；不重试 |
| 1146 | 表不存在 | `METADATA_STALE` | 标记元数据失效；不重试 |
| 1054 | 字段不存在 | `METADATA_STALE` | 同上 |
| 1205 | 锁等待超时 | `DB_LOCK_TIMEOUT` | 可提示稍后；不自动放大超时 |
| 1317 | 查询被中断 | `CANCELLED` | 记录物理取消 |
| 3024 | 超过执行时间 | `QUERY_TIMEOUT` | 失败；提示缩小范围 |
| 2006/2013 | 连接丢失 | `DB_UNAVAILABLE` | 确认旧执行结束后再决定是否重试 |
| 1040 | 连接数满 | `DB_CAPACITY` | 熔断/排队；不重试风暴 |

### 11.6 连接污染与隔离

- 执行中被取消、超时、网络断开的连接，一律标记 `QUARANTINED`，不复用。
- 连接归还池前检查 `conn.closed`、`ping`、是否有未读结果；异常则丢弃。
- 连接池满时排队有上限；超过上限返回 `CAPACITY_EXCEEDED`，不无限等待。
- 业务库压力异常（错误率/延迟）触发熔断：暂停新查询，保留管理与审计能力。

### 11.7 只读的三重保证

1. **账号层**：`chatbi_ro` 只有 `SELECT`，没有写/DDL/FILE 权限。
2. **会话层**：`SET SESSION TRANSACTION READ ONLY`，即使 SQL 注入写语句也会失败。
3. **AST 层**：只允许 `SELECT`/`UNION`，拒绝写/DDL/锁/多语句。

三层任何一层失败都视为缺陷；不能以“账号只读”为由跳过 AST 检查。

---

## 12. 模型网关、用途路由、主备与密钥

### 12.1 用途与配置

| 用途 | 输入 | 输出 | 典型超时 | 备注 |
| --- | --- | --- | --- | --- |
| `UNDERSTAND` | 问题 + 窗口 + 术语 | 结构化条件/澄清 | 10 s | 不生成 SQL |
| `SQL_GEN` | 条件 + 最小 Schema + 指标 | SQP 或候选 SQL | 25 s | 主路径 |
| `SQL_REVIEW` | 候选 SQL + 规则摘要 | 风险提示（非批准） | 10 s | 可选；不替代程序校验 |
| `ANSWER` | 授权摘要 + 图表数据 | 自然语言回答 | 15 s | 仅摘要，不收明细 |

`model_config` 关键字段：`purpose`、`provider`、`base_url`、`model_name`、`enabled`、`priority`（PRIMARY/SECONDARY）、`timeout_ms`、`max_tokens`、`temperature`、`secret_id`、`config_version`、`health_state`。

### 12.2 适配器接口

```python
class ChatModelAdapter(Protocol):
    def chat(
        self,
        *,
        messages: list[Message],
        purpose: Purpose,
        timeout_ms: int,
        max_tokens: int,
        temperature: float,
    ) -> ModelResponse: ...

@dataclass
class ModelResponse:
    text: str
    usage: Usage | None
    finish_reason: str | None
    raw_id: str | None
```

- 第一版实现 `OpenAICompatibleAdapter`；不同供应商的鉴权、路径、错误码在适配器内转换。
- 业务层只依赖 `ModelGateway.chat(purpose, payload, budget)`，不直接使用供应商 SDK。
- 响应必须校验：非空、长度上限、JSON 可解析（SQP 场景）、无禁止内容；不合法则视为模型失败。

### 12.3 路由、主备与熔断

```text
状态：CLOSED（正常） → OPEN（熔断） → HALF_OPEN（探测） → CLOSED
键：route:{purpose}:{config_id}
计数：连续失败次数、最近失败时间、恢复观察窗口
```

| 事件 | 行为 |
| --- | --- |
| 可重试失败（超时、429、5xx） | 任务预算内退避重试；同一配置最多 2 次 |
| 连续失败 ≥ 阈值（建议 3） | 熔断主配置，切备用；记录切换原因 |
| 认证错误/配置无效 | 不重试同一密钥；停用配置并告警 |
| 主备均不可用 | `MODEL_UNAVAILABLE`；若有已授权表格，回答降级为本地说明 |
| 健康探测 | 每 60 s 合成最小请求；HALF_OPEN 成功 N 次后恢复 |
| 切回 | 默认人工确认；自动切回属 DEC-15 |

- 熔断计数只统计模型服务故障；权限拒绝、SQL 安全拒绝、用户澄清不计入。
- 备用模型输出必须经过相同的最小化输入、SQL Gate、权限检查；不得因切换放宽任何规则。
- 每个任务共享 `max_model_calls` 预算；路由重试不得绕过。

### 12.4 密钥加密

采用信封加密：

```text
KEK：部署环境/密钥文件提供的主密钥（32 字节）
DEK：每个 secret 随机生成（32 字节）
密文：AES-256-GCM(DEK, plaintext, AAD=secret_id)
包装：AES-256-GCM(KEK, DEK, AAD=key_version)
存储：ciphertext, nonce, tag, wrapped_dek, key_version, created_at
```

- 密钥只在 `ModelGateway` 调用路径解密；解密后的明文不进入日志、异常、缓存、审计详情。
- 后台接口只返回 `configured=true` + 固定掩码（如 `sk-****abcd`）；空值不表示删除。
- 主密钥轮换：新版本加密新密文；旧版本保留解密能力；轮换需双人操作与审计。
- 备份只包含密文与 `key_version`；主密钥单独托管；无主密钥的备份不可视为可恢复。
- 具体算法、主密钥来源、轮换周期属 DEC-15。

### 12.5 Endpoint 与 SSRF 防护

| 检查 | 规则 |
| --- | --- |
| 协议 | 仅 `https`（内网自建模型可配置 `http` 白名单，需单独批准） |
| 主机 | 必须命中管理员维护的 allowlist；不允许用户输入任意 URL |
| DNS | 解析后拒绝 loopback、私网、链路本地、组播、`169.254.169.254` |
| 重定向 | 禁止跟随；3xx 视为失败 |
| 端口 | 仅 443（或 allowlist 指定端口） |
| 超时 | 连接 3 s、总超时按用途 |
| 响应 | 限制大小；不执行模型返回的 URL/脚本 |

配置页面不能成为“让服务器访问任意地址”的入口；测试连接也走同一 allowlist。

### 12.6 外发数据最小化

`ModelRequestBuilder` 按用途构造 payload：

| 用途 | 允许 | 禁止 |
| --- | --- | --- |
| `UNDERSTAND` | 问题文本、窗口内消息、术语、主题 | 原始明细、完整 Schema、密钥 |
| `SQL_GEN` | 结构化条件、最小 Schema（≤ 8 表/80 字段）、指标定义、关系路径 | 原始明细、其他用户数据、系统表 |
| `SQL_REVIEW` | 候选 SQL、规则摘要、字段用途 | 结果行、凭据 |
| `ANSWER` | 授权聚合摘要、列名、单位、时间范围 | 原始明细、未授权字段、小样本明细 |

- 发送前执行 PII/凭据正则扫描；命中则脱敏或拒绝外发。
- Schema 注释清洗：去除密码、连接串、个人手机号等。
- 小样本聚合：低于 `min_group_size` 不发送；无法证明安全则本地降级。
- 每次调用记录 `purpose, model, prompt_tokens, completion_tokens, latency, status`；默认不记录 prompt/response 正文；如需保存，按 DEC-18 加密并限权。

### 12.7 预算与降级

- 单任务模型调用上限默认 6 次（含理解、生成、修正、总结）。
- 单次调用超时按用途；超时计入预算，不无限重试。
- `ANSWER` 失败不影响已授权表格；返回本地模板摘要 + 警告。
- `SQL_GEN` 失败且无备用 → `MODEL_UNAVAILABLE`；不执行未生成的 SQL。
- 模型限流（429）→ 退避 + 切备用；仍失败则提示稍后重试。

---

## 13. 结果规范化、脱敏、本地摘要与图表

### 13.1 统一结果契约

```json
{
  "query_id": "qry_01J...",
  "status": "SUCCEEDED",
  "conditions_summary": "本部门；2026Q3；报销金额",
  "data_time": "2026-10-22T10:00:00+08:00",
  "columns": [
    {"key": "dept_name", "label": "部门", "type": "string", "unit": null},
    {"key": "amount", "label": "报销金额", "type": "decimal", "unit": "元"}
  ],
  "rows": [
    {"dept_name": "财务部", "amount": "12500.00"}
  ],
  "returned_rows": 1,
  "truncated": false,
  "masked_columns": [],
  "answer": "2026 年第三季度，本部门报销金额为 12,500.00 元。",
  "chart": {
    "type": "bar",
    "x": "dept_name",
    "series": [{"key": "amount", "name": "报销金额"}]
  },
  "warnings": [],
  "trace_id": "trc_..."
}
```

规则：

- `rows` 只包含已授权、已脱敏的投影；不返回被隐藏的原始列。
- 金额/小数使用字符串，避免 JSON 浮点误差；前端按 `type` 格式化。
- `null` 与 `0` 区分；空结果 `rows=[]` 且 `returned_rows=0`。
- `truncated=true` 时必须在 `warnings` 说明“仅展示前 N 行，不代表全量”。
- 普通用户响应不含 SQL、内部表名、trace 以外的调试信息。
- 第一版结果集一次返回，受 `max_rows` 限制；分页/流式结果属 DEC-13，不在本文冻结。

### 13.2 类型规范化

| MySQL 类型 | 内部类型 | 输出规则 |
| --- | --- | --- |
| `TINYINT/SMALLINT/INT/BIGINT` | `integer` | 字符串或 number；超过 JS 安全整数用字符串 |
| `DECIMAL/NUMERIC` | `decimal` | 固定小数位字符串；单位单独给 |
| `FLOAT/DOUBLE` | `number` | 限制精度；NaN/Inf 转为 null + 警告 |
| `DATE` | `date` | `YYYY-MM-DD` |
| `DATETIME/TIMESTAMP` | `datetime` | ISO 8601，带时区偏移 |
| `TIME` | `time` | `HH:MM:SS` |
| `CHAR/VARCHAR/TEXT` | `string` | 去控制字符；长度截断标记 |
| `BLOB/BINARY` | `binary` | 默认不展示；需显式策略 |
| `JSON` | `json` | 只读摘要；不展开为大对象 |

- 列标签优先业务名，其次物理名；单位来自语义层。
- 列顺序按 SELECT 顺序；不按字母排序。
- 重复列名加后缀，前端 key 唯一。

### 13.3 脱敏引擎

```text
apply(result, policies, user):
  for each column in result.columns:
      policy = policies.get(column.id)
      if policy is None: continue
      if not user.can(column, VIEW_RAW):
          column.rows = mask(column.rows, policy.mask_type, policy.mask_pattern)
          result.masked_columns.append(column.key)
      if not user.can(column, EXPORT) and export:
          raise EXPORT_DENIED
```

| 掩码类型 | 示例 | 说明 |
| --- | --- | --- |
| `PARTIAL` | `138****1234`、`a***@b.com` | 保留可识别前缀/后缀 |
| `HASH` | `sha256:...` 前 12 位 | 不可逆；用于关联分析 |
| `BUCKET` | `10,000–20,000` | 区间化，降低精度 |
| `DENY` | 不返回列 | 完全无展示权 |
| `NONE` | 原值 | 仅 `VIEW_RAW` 且用途允许 |

- 脱敏在服务端完成；前端隐藏列不算脱敏。
- 图表、回答、提示气泡、CSV/Excel 全部使用同一脱敏结果。
- 小样本聚合：`COUNT < min_group_size` 时，返回 `NULL`/“样本不足”或合并分组；不得通过差集反推。
- 掩码后的值仍可能被反复过滤/排序推断；字段用途位与查询审计需覆盖。

### 13.4 摘要生成

**默认本地摘要**（不调用模型）：

- 单行单指标：`"2026Q3，本部门报销金额为 12,500.00 元。"`
- 多行：总数、最大值/最小值、Top-N、时间范围；模板化，不编造。
- 空结果：`"当前条件下无记录。"`，不解释为 0。
- 截断：明确“仅基于前 N 行，不代表全量”。

**模型摘要**（可选）：

1. 仅发送授权聚合摘要（列名、单位、行值、时间范围），不发送原始明细。
2. 模型返回文本后，本地做数值一致性校验：关键数字必须能在结果中找到；不一致则丢弃模型文本，回退本地摘要。
3. 摘要不得包含未授权字段、推断出的个人属性、或结果中不存在的数字。
4. 摘要失败不影响表格；`warnings` 记录降级原因。

### 13.5 图表规则

| 数据形态 | 建议图表 | 约束 |
| --- | --- | --- |
| 1 个分类维度 + 1 个数值 | 柱形图 | 类别 ≤ 30；超出用表格 |
| 时间维度 + 1 个数值 | 折线图 | 时间有序；缺失点不插值 |
| ≤ 8 个类别 + 占比 | 饼图 | 仅占比场景；总和有意义 |
| 2 个维度 + 1 个数值 | 分组柱形/热力 | 类别组合 ≤ 50 |
| 其他 | 表格 | 不强行绘图 |

- 服务端返回 `chart` 配置，不返回可执行 JS。
- 前端 ECharts 只接受白名单字段；不执行模型生成的任意 option。
- 图表使用脱敏后的数据；tooltip 不显示被隐藏列。
- 图表类型最终属 DEC-13；以上为默认规则。

### 13.6 空结果、截断与错误

| 情况 | 展示 | 禁止 |
| --- | --- | --- |
| 空结果 | “当前条件下无记录” | 解释为指标为 0 |
| 截断 | “仅展示前 N 行” | 声称完整汇总 |
| 摘要失败 | 表格 + 本地说明 | 编造结论 |
| 图表不适配 | 仅表格 | 强行渲染 |
| 部分列脱敏 | 掩码 + 说明 | 暴露原值 |

---

## 14. 历史、结果快照、指定用户共享与 Excel

### 14.1 历史记录

- 每次成功/失败/取消/拒绝都写 `history_record`；`status` 保留终态。
- 保存：问题、回答、结构化条件、结果摘要、列定义、执行状态、时间、任务/版本、语义版本、权限纪元。
- 历史列表默认仅本人；管理员审计视图需单独授权。
- 查看历史不自动查询业务库；显示“历史结果”和原执行时间。
- 删除为逻辑删除 + 引用失效；异步清理快照/文件；审计不随历史删除。
- 历史长期保存；容量监测与归档属 DEC-10/DE-19。

### 14.2 结果快照

`result_snapshot` 保存某次查询的受控副本：

| 字段 | 说明 |
| --- | --- |
| `storage_key` | 相对键，如 `snapshots/2026/10/22/{uuid}.jsonl.gz` |
| `format` | `jsonl.gz` 第一版；后续可 Parquet |
| `row_count` / `byte_size` | 实际写入量 |
| `truncated` | 是否因上限截断 |
| `scope_proof` | `ROW_LEVEL`、`AGGREGATE_PROVEN`、`UNPROVEN` |
| `scope_meta_json` | 行归属列、分组列、权限纪元、范围指纹 |
| `sha256` | 文件完整性 |
| `expires_at` | 生命周期；DEC-10 |

**范围证明**：

- `ROW_LEVEL`：快照包含每行的本人/部门归属列，且接收者范围可逐行判定。
- `AGGREGATE_PROVEN`：聚合查询的分组维度包含范围列，且每个分组可证明落在接收者范围内。
- `UNPROVEN`：无法逐行/逐组证明（如全局排行榜、去重、模型回答）；只能用于本人查看，禁止共享快照。
- 行归属列与范围指纹只存 `scope_meta_json`，不作为结果列返回，避免向接收者泄露他人归属信息。
- 快照文件采用卷级加密或应用层加密，文件权限 `0600`；加密方式与密钥托管属 DEC-10/19，不在本文冻结。

### 14.3 共享模式

| 模式 | 行为 | 授权 |
| --- | --- | --- |
| `SNAPSHOT` | 展示源查询时刻的授权快照 | 分享者当前权限 + 接收者当前权限 + 范围证明 |
| `RERUN` | 展示查询定义，接收者显式发起新查询 | 接收者身份与当前权限；不借用分享者连接 |

流程：

```text
分享者选择源历史 → 校验源可访问/可分享 → 选择接收用户与模式
→ 校验分享操作权 → 创建 share_grant（ACTIVE）
→ 接收者打开 → 校验共享资格 + 当前数据权限
→ SNAPSHOT：检查 scope_proof；不足则拒绝并提示改用 RERUN
→ RERUN：展示条件摘要，接收者点击“重新查询” → 新任务
→ 审计
```

- 仅指定登录用户；无公开链接、无部门共享、无链接即授权。
- 撤销后阻止新访问；已打开/已下载无法撤回。
- 源历史删除时撤销相关共享；异步清理快照/文件。
- 共享资格不授予额外业务数据权限；接收者权限不足时拒绝，不降级为分享者权限。

### 14.4 快照安全检查

```text
can_share_snapshot(snapshot, recipient):
  if snapshot.scope_proof == UNPROVEN: return false
  if snapshot.truncated and mode == SNAPSHOT:
      # 截断快照仍可共享，但必须标注“非全量”
      pass
  if scope_proof == ROW_LEVEL:
      for each row:
          if row.user_id != recipient.business_user_id
             and row.dept_id not in recipient.business_dept_ids:
              return false
      return true
  if scope_proof == AGGREGATE_PROVEN:
      for each group:
          if group.scope_key not in recipient.scope_keys:
              return false
      return true
  return false
```

- 检查使用**接收者当前权限**，不是分享时权限。
- 权限收缩后，旧快照可能不再可分享；打开时重新判定。
- 无法证明时拒绝快照展示，提示“请使用重新查询模式”，不静默替换模式。

### 14.5 Excel 导出

| 阶段 | 行为 |
| --- | --- |
| 创建 | 校验源结果可访问、导出权、字段原值权、配额 |
| 生成 | 异步任务；从快照/结果读取；重新脱敏；写 `xlsx` |
| 存储 | `/data/exports/{uuid}.xlsx`，`0600`；数据库存相对键与哈希 |
| 下载 | 再次校验当前权限、文件未过期、源未删除；流式返回 |
| 清理 | TTL 到期删除；数据库标记 `EXPIRED` |

安全要求：

- 公式注入：以 `=`, `+`, `-`, `@`, `\t`, `\r` 开头的文本，写入前加单引号或转为文本格式；数字负值保持数值类型。
- 不写隐藏列/隐藏工作表；不把敏感原值写入文档属性、批注、自定义 XML。
- 文件名不含用户输入原样；使用固定前缀 + 时间 + 随机串。
- 导出内容标注条件、时间、单位、截断/脱敏说明。
- 生成与下载分别授权；下载不使用裸存储链接。
- 行数/字节/并发/期限属 DEC-14；第一版只导出当前授权结果，不自动去 LIMIT 全量导出。

### 14.6 生命周期

| 对象 | 默认 | 说明 |
| --- | --- | --- |
| 历史记录 | 长期 | 用户可删；审计独立 |
| 快照 | 可配置 TTL（如 30 天） | 过期后历史仍可看摘要，明细不可用 |
| 导出文件 | 可配置 TTL（如 7 天） | 过期删除；下载拒绝 |
| 临时文件 | 24 小时 | 生成失败/中断清理 |
| 审计 | 独立期限 | DEC-18 |

具体期限属 DEC-10/14/18，不在本文冻结。

---

## 15. 应用数据表、索引、约束与事务

### 15.1 逻辑关系

```text
department 1─n app_user 1─n app_user_role n─1 app_role
app_role 1─n template_grant
app_user 1─n user_exception
app_user 1─n conversation 1─n message
conversation 1─n query_context 1─n query_task 1─n query_attempt
query_task 1─1 history_record 1─n result_snapshot
history_record 1─n share_grant
history_record 1─n export_task 1─1 export_file
sem_version 1─n sem_table 1─n sem_column
sem_table 1─n identity_scope_mapping
sem_column 1─n sensitive_field_policy
model_config 1─1 model_secret
```

### 15.2 约定

- 主键：`CHAR(26)` ULID（字典序近似时间序），避免自增暴露规模。
- 时间：`DATETIME(3)`，UTC；应用层统一生成，不依赖数据库时区。
- 版本：业务表带 `version INT UNSIGNED`，乐观锁。
- 软删除：仅历史/共享等用户对象使用 `deleted_at`；权限、审计不做软删除。
- 外键：核心关系加 FK；高频写入的审计表可省略 FK，靠应用校验。
- 字符集：`utf8mb4`；排序规则 `utf8mb4_0900_ai_ci`。
- JSON：只存结构灵活字段；关键查询字段落列并建索引。

### 15.3 核心 DDL（设计示例）

```sql
CREATE TABLE department (
  id CHAR(26) NOT NULL,
  name VARCHAR(128) NOT NULL,
  parent_id CHAR(26) NULL,
  business_dept_id VARCHAR(64) NULL,
  status ENUM('ACTIVE','DISABLED') NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_department_name (name),
  KEY idx_department_parent (parent_id),
  KEY idx_department_business (business_dept_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE app_user (
  id CHAR(26) NOT NULL,
  login_name VARCHAR(64) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  department_id CHAR(26) NULL,
  business_user_id VARCHAR(64) NULL,
  business_dept_ids JSON NULL,
  status ENUM('ACTIVE','DISABLED','LOCKED') NOT NULL DEFAULT 'ACTIVE',
  failed_login_count INT UNSIGNED NOT NULL DEFAULT 0,
  locked_until DATETIME(3) NULL,
  last_login_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_login (login_name),
  KEY idx_user_department (department_id),
  KEY idx_user_business (business_user_id),
  KEY idx_user_status (status),
  CONSTRAINT fk_user_department FOREIGN KEY (department_id) REFERENCES department (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE app_role (
  id CHAR(26) NOT NULL,
  name VARCHAR(64) NOT NULL,
  description VARCHAR(255) NULL,
  status ENUM('ACTIVE','DISABLED') NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_role_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE app_user_role (
  user_id CHAR(26) NOT NULL,
  role_id CHAR(26) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (user_id, role_id),
  KEY idx_user_role_role (role_id),
  CONSTRAINT fk_user_role_user FOREIGN KEY (user_id) REFERENCES app_user (id),
  CONSTRAINT fk_user_role_role FOREIGN KEY (role_id) REFERENCES app_role (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE permission_template (
  id CHAR(26) NOT NULL,
  role_id CHAR(26) NOT NULL,
  name VARCHAR(64) NOT NULL,
  status ENUM('DRAFT','ACTIVE','DISABLED') NOT NULL DEFAULT 'DRAFT',
  version INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_template_role (role_id),
  CONSTRAINT fk_template_role FOREIGN KEY (role_id) REFERENCES app_role (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE template_grant (
  id CHAR(26) NOT NULL,
  template_id CHAR(26) NOT NULL,
  resource_type ENUM('MODULE','TABLE','COLUMN','TOPIC','METRIC') NOT NULL,
  resource_id VARCHAR(64) NOT NULL,
  action ENUM('VIEW_METADATA','QUERY_SELECT','FILTER','GROUP','SORT',
              'JOIN','EXPORT','VIEW_RAW','CLOUD_SEND','AGGREGATE_SMALL') NOT NULL,
  effect ENUM('ALLOW','DENY') NOT NULL DEFAULT 'ALLOW',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_template_grant (template_id, resource_type, resource_id, action, effect),
  KEY idx_grant_resource (resource_type, resource_id),
  CONSTRAINT fk_grant_template FOREIGN KEY (template_id) REFERENCES permission_template (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_exception (
  id CHAR(26) NOT NULL,
  user_id CHAR(26) NOT NULL,
  resource_type ENUM('MODULE','TABLE','COLUMN','TOPIC','METRIC') NOT NULL,
  resource_id VARCHAR(64) NOT NULL,
  action ENUM('VIEW_METADATA','QUERY_SELECT','FILTER','GROUP','SORT',
              'JOIN','EXPORT','VIEW_RAW','CLOUD_SEND','AGGREGATE_SMALL') NOT NULL,
  effect ENUM('ALLOW','DENY') NOT NULL,
  reason VARCHAR(255) NOT NULL,
  expires_at DATETIME(3) NULL,
  created_by CHAR(26) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_exception (user_id, resource_type, resource_id, action),
  KEY idx_exception_expiry (expires_at),
  CONSTRAINT fk_exception_user FOREIGN KEY (user_id) REFERENCES app_user (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE permission_epoch (
  id TINYINT UNSIGNED NOT NULL,
  epoch BIGINT UNSIGNED NOT NULL,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

```sql
CREATE TABLE sem_version (
  id CHAR(26) NOT NULL,
  version_no BIGINT UNSIGNED NOT NULL,
  source_hash CHAR(64) NOT NULL,
  snapshot_json JSON NOT NULL,
  status ENUM('DRAFT','PUBLISHED','STALE','ARCHIVED') NOT NULL DEFAULT 'DRAFT',
  published_at DATETIME(3) NULL,
  published_by CHAR(26) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_sem_version_no (version_no),
  KEY idx_sem_version_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE sem_table (
  id CHAR(26) NOT NULL,
  version_id CHAR(26) NOT NULL,
  physical_schema VARCHAR(64) NOT NULL,
  physical_name VARCHAR(128) NOT NULL,
  business_name VARCHAR(128) NULL,
  module VARCHAR(64) NULL,
  comment_text VARCHAR(1024) NULL,
  status ENUM('ACTIVE','STALE','DISABLED') NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_sem_table_phys (version_id, physical_schema, physical_name),
  KEY idx_sem_table_module (module),
  CONSTRAINT fk_sem_table_version FOREIGN KEY (version_id) REFERENCES sem_version (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE sem_column (
  id CHAR(26) NOT NULL,
  table_id CHAR(26) NOT NULL,
  physical_name VARCHAR(128) NOT NULL,
  business_name VARCHAR(128) NULL,
  data_type VARCHAR(64) NOT NULL,
  column_type VARCHAR(128) NOT NULL,
  ordinal_position INT UNSIGNED NOT NULL,
  is_nullable TINYINT(1) NOT NULL DEFAULT 1,
  is_primary TINYINT(1) NOT NULL DEFAULT 0,
  comment_text VARCHAR(1024) NULL,
  status ENUM('ACTIVE','STALE','DISABLED') NOT NULL DEFAULT 'ACTIVE',
  PRIMARY KEY (id),
  UNIQUE KEY uk_sem_column_phys (table_id, physical_name),
  KEY idx_sem_column_table (table_id, ordinal_position),
  CONSTRAINT fk_sem_column_table FOREIGN KEY (table_id) REFERENCES sem_table (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE identity_scope_mapping (
  id CHAR(26) NOT NULL,
  table_id CHAR(26) NOT NULL,
  scope_mode ENUM('PUBLIC','SELF','DEPT','SELF_OR_DEPT','DENY') NOT NULL,
  user_column_id CHAR(26) NULL,
  dept_column_id CHAR(26) NULL,
  join_path_json JSON NULL,
  status ENUM('ACTIVE','DISABLED') NOT NULL DEFAULT 'ACTIVE',
  version INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_scope_table (table_id),
  KEY idx_scope_status (status),
  CONSTRAINT fk_scope_table FOREIGN KEY (table_id) REFERENCES sem_table (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE sensitive_field_policy (
  id CHAR(26) NOT NULL,
  column_id CHAR(26) NOT NULL,
  classification ENUM('PII','FINANCE','CREDENTIAL','INTERNAL','PUBLIC') NOT NULL,
  mask_type ENUM('NONE','PARTIAL','HASH','BUCKET','DENY') NOT NULL,
  mask_pattern VARCHAR(128) NULL,
  allowed_purposes INT UNSIGNED NOT NULL,
  min_group_size INT UNSIGNED NOT NULL DEFAULT 5,
  cloud_send TINYINT(1) NOT NULL DEFAULT 0,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_policy_column (column_id),
  CONSTRAINT fk_policy_column FOREIGN KEY (column_id) REFERENCES sem_column (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

```sql
CREATE TABLE conversation (
  id CHAR(26) NOT NULL,
  user_id CHAR(26) NOT NULL,
  title VARCHAR(200) NULL,
  status ENUM('ACTIVE','ARCHIVED','DELETED') NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_conversation_user (user_id, updated_at),
  CONSTRAINT fk_conversation_user FOREIGN KEY (user_id) REFERENCES app_user (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE message (
  id CHAR(26) NOT NULL,
  conversation_id CHAR(26) NOT NULL,
  role ENUM('USER','ASSISTANT','SYSTEM') NOT NULL,
  content MEDIUMTEXT NOT NULL,
  token_count INT UNSIGNED NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_message_conversation (conversation_id, created_at),
  CONSTRAINT fk_message_conversation FOREIGN KEY (conversation_id) REFERENCES conversation (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE query_context (
  id CHAR(26) NOT NULL,
  conversation_id CHAR(26) NOT NULL,
  based_on_query_id CHAR(26) NULL,
  sem_version BIGINT UNSIGNED NOT NULL,
  conditions_json JSON NOT NULL,
  status ENUM('DRAFT','ACTIVE','SUPERSEDED','FAILED_CANDIDATE') NOT NULL DEFAULT 'DRAFT',
  version INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_context_conversation (conversation_id, created_at),
  CONSTRAINT fk_context_conversation FOREIGN KEY (conversation_id) REFERENCES conversation (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE query_task (
  id CHAR(26) NOT NULL,
  user_id CHAR(26) NOT NULL,
  conversation_id CHAR(26) NULL,
  context_id CHAR(26) NULL,
  parent_task_id CHAR(26) NULL,
  question_text TEXT NOT NULL,
  status VARCHAR(32) NOT NULL,
  stage VARCHAR(32) NOT NULL,
  priority TINYINT UNSIGNED NOT NULL DEFAULT 100,
  budget_json JSON NOT NULL,
  budget_used_json JSON NOT NULL,
  perm_epoch BIGINT UNSIGNED NOT NULL,
  sem_version BIGINT UNSIGNED NOT NULL,
  cancel_requested_at DATETIME(3) NULL,
  lease_owner VARCHAR(64) NULL,
  lease_expires_at DATETIME(3) NULL,
  attempt_count TINYINT UNSIGNED NOT NULL DEFAULT 0,
  max_attempts TINYINT UNSIGNED NOT NULL DEFAULT 3,
  next_run_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  error_code VARCHAR(64) NULL,
  trace_id CHAR(32) NOT NULL,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  finished_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  KEY idx_task_claim (status, next_run_at, priority, created_at),
  KEY idx_task_user (user_id, created_at),
  KEY idx_task_conversation (conversation_id, created_at),
  KEY idx_task_lease (lease_expires_at),
  CONSTRAINT fk_task_user FOREIGN KEY (user_id) REFERENCES app_user (id),
  CONSTRAINT fk_task_conversation FOREIGN KEY (conversation_id) REFERENCES conversation (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE query_attempt (
  id CHAR(26) NOT NULL,
  task_id CHAR(26) NOT NULL,
  attempt_no TINYINT UNSIGNED NOT NULL,
  stage VARCHAR(32) NOT NULL,
  worker_id VARCHAR(64) NULL,
  status ENUM('RUNNING','SUCCEEDED','FAILED','LOST','CANCELLED') NOT NULL,
  model_calls INT UNSIGNED NOT NULL DEFAULT 0,
  sql_hash CHAR(64) NULL,
  connection_id BIGINT UNSIGNED NULL,
  physical_cancel ENUM('NOT_APPLICABLE','CONFIRMED','FAILED','UNKNOWN')
      NOT NULL DEFAULT 'NOT_APPLICABLE',
  error_code VARCHAR(64) NULL,
  detail_json JSON NULL,
  started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  finished_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_attempt_task_no (task_id, attempt_no),
  KEY idx_attempt_task (task_id, started_at),
  CONSTRAINT fk_attempt_task FOREIGN KEY (task_id) REFERENCES query_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE task_outbox (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  aggregate_type VARCHAR(32) NOT NULL,
  aggregate_id CHAR(26) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  payload_json JSON NOT NULL,
  status ENUM('PENDING','SENT','FAILED') NOT NULL DEFAULT 'PENDING',
  available_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  sent_at DATETIME(3) NULL,
  last_error VARCHAR(512) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_outbox_pending (status, available_at),
  KEY idx_outbox_aggregate (aggregate_type, aggregate_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

```sql
CREATE TABLE history_record (
  id CHAR(26) NOT NULL,
  user_id CHAR(26) NOT NULL,
  conversation_id CHAR(26) NULL,
  task_id CHAR(26) NOT NULL,
  question_text TEXT NOT NULL,
  answer_text MEDIUMTEXT NULL,
  conditions_json JSON NOT NULL,
  columns_json JSON NOT NULL,
  result_summary_json JSON NULL,
  status VARCHAR(32) NOT NULL,
  data_time DATETIME(3) NULL,
  sem_version BIGINT UNSIGNED NOT NULL,
  perm_epoch BIGINT UNSIGNED NOT NULL,
  deleted_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_history_task (task_id),
  KEY idx_history_user (user_id, created_at),
  KEY idx_history_deleted (deleted_at),
  CONSTRAINT fk_history_user FOREIGN KEY (user_id) REFERENCES app_user (id),
  CONSTRAINT fk_history_task FOREIGN KEY (task_id) REFERENCES query_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE result_snapshot (
  id CHAR(26) NOT NULL,
  history_id CHAR(26) NOT NULL,
  storage_key VARCHAR(255) NOT NULL,
  format ENUM('JSONL_GZ','PARQUET') NOT NULL DEFAULT 'JSONL_GZ',
  row_count INT UNSIGNED NOT NULL,
  byte_size BIGINT UNSIGNED NOT NULL,
  truncated TINYINT(1) NOT NULL DEFAULT 0,
  scope_proof ENUM('ROW_LEVEL','AGGREGATE_PROVEN','UNPROVEN') NOT NULL,
  scope_meta_json JSON NOT NULL,
  sha256 CHAR(64) NOT NULL,
  expires_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_snapshot_history (history_id),
  KEY idx_snapshot_expiry (expires_at),
  CONSTRAINT fk_snapshot_history FOREIGN KEY (history_id) REFERENCES history_record (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE share_grant (
  id CHAR(26) NOT NULL,
  source_history_id CHAR(26) NOT NULL,
  shared_by CHAR(26) NOT NULL,
  recipient_user_id CHAR(26) NOT NULL,
  mode ENUM('SNAPSHOT','RERUN') NOT NULL,
  status ENUM('ACTIVE','REVOKED','EXPIRED') NOT NULL DEFAULT 'ACTIVE',
  expires_at DATETIME(3) NULL,
  revoked_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_share_source (source_history_id),
  KEY idx_share_recipient (recipient_user_id, status),
  CONSTRAINT fk_share_history FOREIGN KEY (source_history_id) REFERENCES history_record (id),
  CONSTRAINT fk_share_recipient FOREIGN KEY (recipient_user_id) REFERENCES app_user (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE export_task (
  id CHAR(26) NOT NULL,
  user_id CHAR(26) NOT NULL,
  source_history_id CHAR(26) NOT NULL,
  status ENUM('QUEUED','RUNNING','SUCCEEDED','FAILED','EXPIRED','CANCELLED') NOT NULL,
  columns_json JSON NOT NULL,
  row_limit INT UNSIGNED NOT NULL,
  file_id CHAR(26) NULL,
  error_code VARCHAR(64) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  finished_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  KEY idx_export_user (user_id, created_at),
  KEY idx_export_status (status, created_at),
  CONSTRAINT fk_export_user FOREIGN KEY (user_id) REFERENCES app_user (id),
  CONSTRAINT fk_export_history FOREIGN KEY (source_history_id) REFERENCES history_record (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE export_file (
  id CHAR(26) NOT NULL,
  storage_key VARCHAR(255) NOT NULL,
  filename VARCHAR(255) NOT NULL,
  byte_size BIGINT UNSIGNED NOT NULL,
  sha256 CHAR(64) NOT NULL,
  expires_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_export_file_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

```sql
CREATE TABLE model_config (
  id CHAR(26) NOT NULL,
  purpose ENUM('UNDERSTAND','SQL_GEN','SQL_REVIEW','ANSWER') NOT NULL,
  provider VARCHAR(64) NOT NULL,
  base_url VARCHAR(512) NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  priority ENUM('PRIMARY','SECONDARY') NOT NULL,
  timeout_ms INT UNSIGNED NOT NULL,
  max_tokens INT UNSIGNED NOT NULL,
  temperature DECIMAL(3,2) NOT NULL DEFAULT 0.00,
  secret_id CHAR(26) NULL,
  config_version INT UNSIGNED NOT NULL DEFAULT 1,
  health_state ENUM('UNKNOWN','HEALTHY','DEGRADED','OPEN') NOT NULL DEFAULT 'UNKNOWN',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
      ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_model_purpose (purpose, enabled, priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE model_secret (
  id CHAR(26) NOT NULL,
  ciphertext BLOB NOT NULL,
  nonce BLOB NOT NULL,
  tag BLOB NOT NULL,
  wrapped_dek BLOB NOT NULL,
  key_version VARCHAR(32) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  rotated_at DATETIME(3) NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE audit_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  occurred_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  trace_id CHAR(32) NOT NULL,
  user_id CHAR(26) NULL,
  task_id CHAR(26) NULL,
  event_type VARCHAR(64) NOT NULL,
  stage VARCHAR(32) NULL,
  status VARCHAR(32) NULL,
  latency_ms INT UNSIGNED NULL,
  row_count INT UNSIGNED NULL,
  error_code VARCHAR(64) NULL,
  detail_json JSON NULL,
  ip_hash CHAR(64) NULL,
  PRIMARY KEY (id),
  KEY idx_audit_time (occurred_at),
  KEY idx_audit_user (user_id, occurred_at),
  KEY idx_audit_task (task_id, occurred_at),
  KEY idx_audit_type (event_type, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

### 15.4 其余表字段摘要

| 表 | 关键字段 | 索引/约束 |
| --- | --- | --- |
| `sem_relation` | `id, from_table_id, from_column_id, to_table_id, to_column_id, cardinality, source(FK/MANUAL), status` | 唯一 `(from_table_id, from_column_id, to_table_id, to_column_id)` |
| `sem_term` | `id, name, synonyms_json, target_type, target_id, module, status, version` | 唯一 `(name, module)` |
| `sem_metric` | `id, name, expression, grain, unit, time_column_id, filter_json, version, status` | 唯一 `(name, version)` |
| `sem_topic` | `id, name, module, description, example_questions_json, status, version` | 唯一 `(name, version)` |
| `data_source` | `id, name, host_ref, port, schema_name, secret_ref, read_mode, status` | 唯一 `(name)` |
| `task_dispatch` | `dispatch_id, task_id, queue, status, created_at, last_error` | 唯一 `dispatch_id`；索引 `task_id` |
| `idempotency_key` | `user_id, scope, key, request_hash, response_json, expires_at` | 唯一 `(user_id, scope, key)` |
| `admin_audit` | `id, actor_id, action, target_type, target_id, before_json, after_json, trace_id, created_at` | 索引 `(actor_id, created_at)`、`(target_type, target_id)` |
| `alert_event` | `id, type, severity, status, summary, trace_id, created_at, acknowledged_at` | 索引 `(status, created_at)`、`(type, created_at)` |

### 15.5 事务边界

| 操作 | 事务 | 说明 |
| --- | --- | --- |
| 创建任务 | 单事务：`query_task` + `query_context` + `audit_event` + `task_outbox` | 提交后由分发器投递 |
| 状态迁移 | 单条 `UPDATE ... WHERE status/version` | 乐观锁；失败重读 |
| 权限发布 | `permission_epoch` + 模板/例外 + 审计 | 同一事务；提交即生效 |
| 元数据发布 | `sem_version` + 表/字段/关系 + 审计 | 旧版本归档同事务 |
| 结果发布 | `history_record` + `result_snapshot` + `query_task` 终态 + 审计 | 快照文件先写临时名，成功后原子 rename |
| 共享创建 | `share_grant` + 审计 | 校验源/接收者/模式 |
| 导出下载 | 只读校验 + 审计 | 不修改文件；记录访问 |

### 15.6 数据保留

- 审计与历史分离；删除历史不删审计。
- 任务表可按月归档到冷表；归档前先完成终态与审计。
- 快照/文件 TTL 清理是异步任务；清理失败告警，不静默。
- 备份保留策略属 DEC-19。

---

## 16. API、事件协议和错误契约

### 16.1 公共约定

- 基础路径：`/api`（与功能设计文档一致）；版本通过 `X-API-Version` 或后续前缀演进，第一版不强制。
- 认证：会话 Cookie；除 `POST /api/auth/login` 外均要求登录。
- CSRF：所有非 GET/HEAD 请求要求 `X-CSRF-Token`。
- 幂等：提交/重查/导出支持 `Idempotency-Key`。
- 追踪：响应头 `X-Trace-Id`；错误体含 `trace_id`。
- 分页：游标 `cursor` + `limit`；不提供无界 `offset`。
- 内容类型：`application/json; charset=utf-8`；文件下载 `application/octet-stream`。
- 普通用户响应不含 SQL、内部表名、堆栈、密钥。

### 16.2 端点清单

| 能力 | 方法与路径 | 请求要点 | 响应要点 | 授权 |
| --- | --- | --- | --- | --- |
| 登录 | `POST /api/auth/login` | 登录名、密码 | 用户、CSRF、过期时间 | 无 |
| 登出 | `POST /api/auth/logout` | — | 204 | 会话 |
| 当前身份 | `GET /api/me` | — | 用户、部门、角色、功能 | 会话 |
| 会话续期 | `POST /api/auth/refresh` | CSRF | 新过期时间 | 会话 |
| 用户列表 | `GET /api/admin/users` | 搜索、游标 | 分页 | 用户管理权 |
| 创建用户 | `POST /api/admin/users` | 登录名、部门、角色 | 用户 ID | 用户管理权 |
| 修改用户 | `PATCH /api/admin/users/{id}` | 显示名、部门、状态 | 更新结果 | 用户管理权 |
| 部门/角色 | `GET/POST/PATCH /api/admin/departments`、`/roles` | 名称、状态 | 列表/结果 | 对应管理权 |
| 权限模板 | `GET/POST/PATCH /api/admin/permission-templates` | 资源、动作、效果 | 版本/影响 | 权限管理权 |
| 用户例外 | `GET/POST/DELETE /api/admin/users/{id}/exceptions` | 资源、动作、理由 | 结果 | 权限管理权 |
| 元数据同步 | `POST /api/admin/metadata/sync` | 模式（全量/增量） | 任务 ID | 元数据管理权 |
| 元数据导入预览 | `POST /api/admin/metadata/import-preview` | 文件 | 预览 ID、差异 | 元数据管理权 |
| 元数据导入应用 | `POST /api/admin/metadata/import-apply` | 预览 ID | 应用报告 | 元数据管理权 |
| 术语/指标/主题 | `/api/admin/terms`、`/metrics`、`/topics` | 定义、版本、状态 | 列表/结果 | 语义管理权 |
| 主题列表 | `GET /api/topics` | — | 已发布可访问主题 | 查询权 |
| 创建会话 | `POST /api/conversations` | 标题 | 会话 ID | 登录 |
| 会话列表 | `GET /api/conversations` | 游标 | 列表 | 本人 |
| 提交问题 | `POST /api/conversations/{id}/queries` | 问题、主题、幂等键 | 任务/查询 ID | 会话归属、查询权 |
| 任务状态 | `GET /api/queries/{id}` | — | 状态、阶段、警告 | 本人/运维 |
| 任务事件 | `GET /api/queries/{id}/events` | SSE | 状态/结果/错误 | 本人 |
| 取消任务 | `POST /api/queries/{id}/cancel` | — | 202/终态 | 本人/运维 |
| 获取结果 | `GET /api/queries/{id}/result` | — | 结果契约 | 本人、当前权限 |
| 历史列表 | `GET /api/history` | 时间、状态、游标 | 列表 | 本人 |
| 历史详情 | `GET /api/history/{id}` | — | 问题/回答/摘要 | 本人、当前权限 |
| 删除历史 | `DELETE /api/history/{id}` | — | 204 | 本人 |
| 历史重查 | `POST /api/history/{id}/rerun` | 日期选项、幂等键 | 新任务 | 记录访问权、查询权 |
| 创建共享 | `POST /api/shares` | 源历史、接收者、模式 | 共享 ID | 源访问权、分享权 |
| 撤销共享 | `DELETE /api/shares/{id}` | — | 204 | 分享者 |
| 访问共享 | `GET /api/shares/{id}` | — | 快照或查询定义 | 接收者、当前权限 |
| 共享重查 | `POST /api/shares/{id}/rerun` | 幂等键 | 新任务 | 接收者、查询权 |
| 创建导出 | `POST /api/exports` | 源查询、列、幂等键 | 导出任务 ID | 导出权、原值权 |
| 导出状态 | `GET /api/exports/{id}` | — | 状态、文件信息 | 本人 |
| 下载文件 | `GET /api/exports/{id}/download` | — | 文件流 | 当前权限、文件有效 |
| 模型配置 | `GET/POST/PATCH /api/admin/models` | 用途、地址、模型、密钥 | 掩码、健康 | 模型管理权 |
| 模型测试 | `POST /api/admin/models/{id}/test` | — | 测试任务/状态（不含密钥） | 模型管理权 |
| 审计查询 | `GET /api/admin/audits` | 时间、类型、用户 | 脱敏记录 | 审计权 |
| 运行指标 | `GET /api/admin/metrics-view` | 时间范围 | 聚合指标 | 运维/审计权 |

### 16.3 请求/响应示例

**登录**

```http
POST /api/auth/login HTTP/1.1
Content-Type: application/json

{"login_name": "zhangsan", "password": "用户输入"}
```

```http
HTTP/1.1 200 OK
Set-Cookie: __Host-chatbi_session=...; HttpOnly; Secure; SameSite=Lax; Path=/
Set-Cookie: chatbi_csrf=...; Secure; SameSite=Lax; Path=/

{
  "user": {
    "id": "usr_01J...",
    "display_name": "张三",
    "department": {"id": "dep_01J...", "name": "财务部"},
    "roles": [{"id": "role_01J...", "name": "业务用户"}]
  },
  "csrf_token": "...",
  "expires_at": "2026-10-22T21:00:00Z"
}
```

**提交问题**

```http
POST /api/conversations/conv_01J.../queries HTTP/1.1
Content-Type: application/json
Idempotency-Key: 7f3c...

{"question": "统计本部门上季度报销金额", "topic_id": null}
```

```http
HTTP/1.1 202 Accepted

{
  "task_id": "tsk_01J...",
  "query_id": "qry_01J...",
  "status": "QUEUED",
  "trace_id": "trc_01J..."
}
```

**SSE**

```text
event: state
data: {"status":"UNDERSTANDING","stage":"UNDERSTANDING","progress":0.15}

event: state
data: {"status":"EXECUTING","stage":"EXECUTING","progress":0.60}

event: result
data: {"query_id":"qry_01J...","status":"SUCCEEDED","returned_rows":1,"truncated":false}

event: heartbeat
data: {"ts":"2026-10-22T10:00:15Z"}
```

- SSE 连接要求登录；跨域不开放。
- 断开后客户端先 `GET /api/queries/{id}` 对齐状态，再重新订阅。
- 结果事件只发摘要，完整结果由 `/result` 获取；避免大 payload 阻塞事件流。

**错误**

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "当前权限不足，请调整问题或联系管理员",
    "trace_id": "trc_01J...",
    "details": null
  }
}
```

### 16.4 SSE 事件类型

| 事件 | 数据 | 说明 |
| --- | --- | --- |
| `state` | `status, stage, progress, warnings` | 状态变化 |
| `delta` | `text` | 回答流式片段（可选） |
| `result` | `query_id, status, returned_rows, truncated` | 结果可获取 |
| `error` | `code, message, trace_id` | 终态错误 |
| `heartbeat` | `ts` | 保活，15 秒 |

### 16.5 错误码

| 错误码 | HTTP | 含义 |
| --- | --- | --- |
| `AUTH_REQUIRED` | 401 | 未登录/会话失效 |
| `AUTH_FAILED` | 401 | 登录失败（统一提示） |
| `ACCOUNT_DISABLED` | 403 | 账号禁用 |
| `CSRF_INVALID` | 403 | CSRF 校验失败 |
| `OBJECT_NOT_ACCESSIBLE` | 404 | 对象不存在或无权（不泄露存在性） |
| `PERMISSION_DENIED` | 403 | 业务权限不足 |
| `NEEDS_CLARIFICATION` | 200/422 | 需要澄清（任务态） |
| `METADATA_UNAVAILABLE` | 503 | 元数据不可用 |
| `METADATA_STALE` | 409 | 元数据失效 |
| `SQL_UNSAFE` / `SQL_UNSUPPORTED` | 422 | SQL 安全拒绝 |
| `RATE_LIMITED` | 429 | 限流 |
| `CAPACITY_EXCEEDED` | 503 | 容量超限 |
| `MODEL_UNAVAILABLE` | 503 | 模型不可用 |
| `QUERY_TIMEOUT` | 504 | 查询超时 |
| `DB_UNAVAILABLE` | 503 | 数据库不可用 |
| `CANCEL_REQUESTED` / `CANCELLED` | 202/200 | 取消状态 |
| `RESULT_EXPIRED` / `EXPORT_EXPIRED` | 410 | 结果/文件过期 |
| `IDEMPOTENCY_CONFLICT` | 409 | 幂等键冲突 |
| `INTERNAL_ERROR` | 500 | 通用错误（带 trace） |

### 16.6 OpenAPI 与契约测试

- FastAPI 自动生成 OpenAPI 3.1；前端用 `openapi-typescript` 生成类型。
- 契约测试校验：请求/响应字段、错误码、枚举、必填项。
- 任何破坏性变更需版本化；新增可选字段不视为破坏。
- 接口文档不暴露内部表名、SQL 模板、密钥字段。

---

## 17. 限流、并发、缓存、预算与性能

### 17.1 限流

采用 Redis 令牌桶，按“用户 + 全局 + 端点类别”三层：

| 层级 | 键 | 建议初始值 | 超限行为 |
| --- | --- | --- | --- |
| 用户提交 | `rl:q:{user_id}` | 10 次/分钟，突发 3 | 429，返回等待秒数 |
| 用户并发 | `cc:q:{user_id}` | 1–2 | 排队或 429 |
| 全局提交 | `rl:q:global` | 60 次/分钟 | 429/503 |
| 全局 SQL 并发 | `cc:sql:global` | 8 | 排队，队列有界 |
| 导出并发 | `cc:export` | 2 | 排队 |
| 登录失败 | `rl:login:{ip_hash}` | 10 次/10 分钟 | 429/锁定（DEC-01） |

- 令牌桶用 Lua 原子执行；返回 `remaining`、`reset_at`。
- 限流键带过期时间，不无限增长。
- 限流不是权限；超限不创建任务、不写业务结果，只写审计。
- 过载时优先保护业务库：排队有上限，超过直接拒绝。

### 17.2 并发控制

```text
API 受理：检查用户并发计数（Redis）→ 通过则创建任务
Worker 领取：DB 租约保证同一任务只有一个 worker
执行器：全局 SQL 信号量（Redis ZSET 租约）→ 获取后才连业务库
释放：任务终态/取消/超时/异常均释放；租约过期由清理任务回收
```

- 并发计数是“软限制”，DB 租约与执行器信号量是“硬保护”；两者都保留。
- 任务失败/取消必须释放计数；使用带 TTL 的租约，避免进程崩溃后永久占用。
- 单用户并发默认 1–2；管理员/运维不享受无限并发。
- 导出与问数分队列，避免大文件生成拖垮交互查询。

### 17.3 缓存

| 缓存 | 键 | TTL | 失效 |
| --- | --- | --- | --- |
| 会话 | `sess:{id}` | 空闲 30 分钟，绝对 12 小时 | 登出/禁用/过期 |
| 有效权限 | `perm:{user_id}:{epoch}` | 5 分钟 | 纪元变化即失效 |
| 语义快照 | `sem:{version}` | 10 分钟 | 新版本发布 |
| 主题列表 | `topics:{user_id}:{epoch}` | 5 分钟 | 权限/主题变化 |
| 限流桶 | `rl:*` | 窗口长度 | 自然过期 |

- **不缓存查询结果**：业务数据实时性无法保证；历史/快照是显式对象，不是缓存。
- 缓存键必须含权限纪元/语义版本；禁止跨用户共享结果缓存。
- Redis 故障时会话不可用，API 拒绝新请求；worker 已领取任务可继续（不依赖 Redis 读权限，但取消通知可能延迟，需 DB 轮询兜底）。
- 缓存不做唯一事实源；任何缓存丢失都应能回源重建。

### 17.4 端到端预算

以“常规问题、1 次 SQL、1 次摘要”为例（设计目标，不是 SLA）：

| 阶段 | P50 目标 | P95 目标 | 说明 |
| --- | --- | --- | --- |
| 认证/参数/限流 | 20 ms | 50 ms | 含会话与权限缓存 |
| 上下文/检索 | 200 ms | 500 ms | 关键词 + 外键扩展 |
| 模型生成 SQP/SQL | 2,000 ms | 4,000 ms | 依赖供应商 |
| SQL Gate | 80 ms | 200 ms | 纯本地 AST |
| 业务库执行 | 800 ms | 3,000 ms | 依赖数据量与索引 |
| 结果处理/脱敏 | 100 ms | 300 ms | 1,000 行内 |
| 摘要生成 | 800 ms | 2,000 ms | 可降级本地 |
| 合计 | 4,000 ms | 9,000 ms | 复杂查询可更久 |

- 5–10 秒是初始目标，不是承诺；必须用固定问题集、样本数据、模型版本、网络与缓存状态测量。
- 分阶段记录耗时，定位“模型慢/数据库慢/检索慢/摘要慢”。
- 冷启动（无缓存）与热缓存分开报告；不把热缓存结果当作常规。
- 复杂查询允许更久，但必须有硬超时与预算。

### 17.5 压测方法

| 项目 | 方法 |
| --- | --- |
| 数据集 | 合成/脱敏，至少两部门、敏感字段、外键、无外键表、边界数据 |
| 问题集 | 常规/复杂/歧义/越权/空结果，各若干 |
| 工具 | k6 或 Locust；记录 P50/P95/P99、错误率、超时率 |
| 并发 | 1、5、10、20 虚拟用户；不超过批准的生产负载 |
| 模型 | 固定版本与超时；模拟 429/500/超时 |
| 数据库 | 只读副本/测试库；记录慢查询与连接数 |
| 输出 | 分阶段耗时、瓶颈、资源占用、失败分类 |

压测结果只对测试环境有效；生产放行需 DBA 与项目负责人确认（DEC-20/21）。

### 17.6 性能优化顺序

1. 减少不必要的模型调用：能规则解析的澄清/条件补丁不调用模型。
2. 缩小 Schema 检索范围与提示词 token。
3. 为行范围包装后的查询确认索引；必要时与 DBA 评审。
4. 结果集上限与流式读取，避免大结果拖垮内存。
5. 摘要降级为本地模板，减少一次模型往返。
6. 缓存只用于权限/语义/主题，不用于结果。

---

## 18. 日志审计、监控告警与异常恢复

### 18.1 审计事件

| 类别 | 事件 | 必填字段 |
| --- | --- | --- |
| 认证 | `AUTH_LOGIN`、`AUTH_LOGOUT`、`AUTH_FAILED`、`SESSION_REVOKED` | 用户、时间、IP 哈希、结果 |
| 查询 | `QUERY_SUBMITTED`、`QUERY_STAGE`、`QUERY_REJECTED`、`QUERY_EXECUTED`、`QUERY_CANCELLED`、`RESULT_PUBLISHED` | 任务、attempt、阶段、耗时、错误码 |
| 数据访问 | `HISTORY_VIEWED`、`HISTORY_DELETED`、`SHARE_CREATED`、`SHARE_ACCESSED`、`SHARE_REVOKED`、`EXPORT_CREATED`、`EXPORT_DOWNLOADED` | 对象 ID、模式、权限校验结果 |
| 管理 | `ADMIN_USER_CHANGED`、`ADMIN_PERMISSION_CHANGED`、`ADMIN_MODEL_CHANGED`、`METADATA_SYNC`、`SEMANTIC_PUBLISHED` | 操作者、目标、变更前后（脱敏） |
| 运行 | `MODEL_SWITCHED`、`DB_DEGRADED`、`BACKUP_RESULT`、`ALERT_RAISED` | 服务、原因、影响范围 |

- 审计写入与业务事务尽量同库；安全关键事件（权限变更、导出下载、共享访问）必须可靠落盘。
- 审计失败时：安全关键操作失败关闭（拒绝），普通查询可继续但告警。
- 审计读取需独立授权；审计详情中的敏感值脱敏；SQL 原文按 DEC-18 决定是否加密保存。
- 审计表只追加：应用运行账号无 `UPDATE`/`DELETE` 权限；归档/清理走受控运维任务并留痕。

### 18.2 日志规范

```json
{
  "ts": "2026-10-22T10:00:00.123Z",
  "level": "INFO",
  "service": "worker",
  "trace_id": "trc_01J...",
  "task_id": "tsk_01J...",
  "user_id_hash": "sha256:...",
  "event": "query.stage",
  "stage": "EXECUTING",
  "latency_ms": 812,
  "error_code": null
}
```

- 禁止记录：密码、Cookie、Authorization、API Key、数据库连接串、完整结果行。
- SQL 只记录哈希/指纹；需要审计原文时写加密字段并限权。
- 用户问题文本默认不入普通日志；审计表按权限保存。
- 日志脱敏规则集中配置，新增字段必须评审。

### 18.3 指标

| 指标 | 类型 | 标签 |
| --- | --- | --- |
| `chatbi_query_total` | Counter | `status`、`stage` |
| `chatbi_query_duration_seconds` | Histogram | `stage` |
| `chatbi_model_calls_total` | Counter | `purpose`、`status`、`model` |
| `chatbi_model_latency_seconds` | Histogram | `purpose`、`model` |
| `chatbi_sql_reject_total` | Counter | `code` |
| `chatbi_db_rows_returned` | Histogram | — |
| `chatbi_queue_depth` | Gauge | `queue` |
| `chatbi_worker_busy` | Gauge | `worker` |
| `chatbi_permission_denied_total` | Counter | `reason` |
| `chatbi_export_total` | Counter | `status` |
| `chatbi_outbox_pending` | Gauge | — |
| `chatbi_lease_expired_total` | Counter | `stage` |

### 18.4 告警规则（建议）

| 告警 | 条件 | 级别 | 处置 |
| --- | --- | --- | --- |
| 模型失败率高 | 5 分钟失败率 > 20% | P1 | 检查主备/供应商/密钥 |
| 主备均不可用 | `MODEL_UNAVAILABLE` 连续 3 次 | P0 | 降级回答、通知 |
| 数据库错误率高 | 5 分钟 > 5% | P0 | 熔断新查询、DBA |
| 队列积压 | `queue_depth > 50` 持续 10 分钟 | P1 | 扩容/限流 |
| Outbox 积压 | `outbox_pending > 100` 持续 5 分钟 | P1 | 检查分发器/Redis |
| 租约过期激增 | 10 分钟 > 10 次 | P1 | 检查 worker/长查询 |
| 审计写入失败 | 任意安全关键事件失败 | P0 | 停止相关操作 |
| 备份失败 | 任意一次失败 | P1 | 重试/检查存储 |
| 密钥解密失败 | 任意一次 | P0 | 检查主密钥/轮换 |
| 文件卷使用率 | > 80% | P1 | 清理/扩容 |

告警渠道、阈值、确认与升级流程属 DEC-18；本文不声称已配置任何渠道。

### 18.5 降级矩阵

| 故障 | 影响 | 降级行为 |
| --- | --- | --- |
| 模型供应商不可用 | 无法生成 SQL/摘要 | 主备切换；仍不可用则失败或仅表格+本地摘要 |
| Redis 不可用 | 会话/限流/缓存不可用 | 新请求拒绝；worker 已领取任务继续；取消依赖 DB 轮询 |
| 应用 MySQL 不可用 | 任务/权限/历史不可用 | 停止受理；不伪造结果 |
| 业务 MySQL 不可用 | 查询失败 | 历史查看可用；提示稍后重试 |
| 文件卷满 | 快照/导出失败 | 问数可继续但无快照；导出拒绝 |
| 元数据同步失败 | 结构可能过期 | 保留旧版本；标记 STALE；不执行失效查询 |
| 审计写入失败 | 合规风险 | 安全关键操作失败关闭；普通查询告警 |

### 18.6 追踪

- 每个请求生成 `trace_id`；任务、attempt、模型调用、SQL 执行、审计共用。
- 日志、指标、审计、错误响应都能按 `trace_id` 关联。
- 普通用户只看到 `trace_id`，不看到内部堆栈。
- 追踪系统可选 OpenTelemetry；第一版可用 trace_id + 结构化日志。

---

## 19. Docker Compose、配置与网络安全

### 19.1 服务拓扑

```text
Internet/内网用户
   │ 443
┌──▼─────────┐
│ nginx      │  edge 网络
└──┬─────────┘
   │ 8000
┌──▼─────────┐     ┌──────────────┐
│ api        │────▶│ redis        │  app 网络
└──┬─────────┘     └──────┬───────┘
   │                      │
   │  ┌───────────────────┘
┌──▼─────────┐     ┌──────────────┐
│ worker     │────▶│ mysql        │  data 网络
└──┬─────────┘     └──────────────┘
   │
   └──▶ 业务 MySQL（外部，仅 worker 可达）
```

### 19.2 Compose 示例（设计示例，不含真实密钥）

```yaml
services:
  nginx:
    image: nginx:1.26-alpine
    ports:
      - "443:443"
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./deploy/certs:/etc/nginx/certs:ro
      - ./web/dist:/usr/share/nginx/html:ro
    networks: [edge, app]
    depends_on:
      api:
        condition: service_healthy
    restart: unless-stopped

  api:
    image: chatbi:${CHATBI_VERSION:-dev}
    build: .
    command: ["uvicorn", "chatbi.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
    env_file: [".env"]
    volumes:
      - chatbi_data:/data
    networks: [app, data]
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
      interval: 15s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  worker:
    image: chatbi:${CHATBI_VERSION:-dev}
    build: .
    command: ["celery", "-A", "chatbi.workers.celery_app", "worker",
              "-Q", "chatbi.query,chatbi.export,chatbi.maintenance", "-c", "4"]
    env_file: [".env"]
    volumes:
      - chatbi_data:/data
    networks: [app, data, egress]
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "celery", "-A", "chatbi.workers.celery_app", "inspect", "ping"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  beat:
    image: chatbi:${CHATBI_VERSION:-dev}
    build: .
    command: ["celery", "-A", "chatbi.workers.celery_app", "beat", "--loglevel=INFO"]
    env_file: [".env"]
    networks: [app, data]
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  mysql:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: chatbi
      MYSQL_USER: chatbi
      MYSQL_PASSWORD: ${APP_DB_PASSWORD}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
    volumes:
      - mysql_data:/var/lib/mysql
      - ./deploy/mysql.cnf:/etc/mysql/conf.d/chatbi.cnf:ro
    networks: [data]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-p${MYSQL_ROOT_PASSWORD}"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  redis:
    image: redis:7.2-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory-policy", "noeviction"]
    volumes:
      - redis_data:/data
    networks: [app, data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped

networks:
  edge:
  app:
  data:
    internal: true
  egress:

volumes:
  mysql_data:
  redis_data:
  chatbi_data:
```

> 示例未包含真实密码、证书、业务库连接串；`${...}` 由部署环境注入。`egress` 仅挂到 worker，供其访问云端模型与业务 MySQL；如业务库走专线或独立路由，可替换为宿主路由。`api`、`beat` 不直接出网。

### 19.3 端口与网络

| 端口 | 暴露范围 | 用途 |
| --- | --- | --- |
| 443 | 用户网段 | HTTPS |
| 80 | 可选，仅跳转 443 | 不建议明文 |
| 8000 | 仅 nginx | API |
| 3306 | 仅 data 网络 | 应用 MySQL |
| 6379 | 仅 app/data 网络 | Redis |
| 业务 MySQL 3306 | 仅 worker 网段 | 只读查询 |

- 业务 MySQL 不加入 Compose 网络；通过宿主机路由/防火墙白名单访问。
- Nginx 配置安全响应头：`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、CSP（按前端资源调整）。
- TLS 1.2/1.3；证书更新流程属 DEC-21。

### 19.4 配置项

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `production` | 环境 |
| `APP_DB_HOST` | `mysql` | 应用库 |
| `APP_DB_PASSWORD` | `${...}` | 由密钥注入 |
| `REDIS_URL` | `redis://redis:6379/0` | 会话/缓存/broker |
| `BUSINESS_DB_HOST` | `10.x.x.x` | 业务库（示例占位） |
| `BUSINESS_DB_USER` | `chatbi_ro` | 只读账号 |
| `BUSINESS_DB_PASSWORD` | `${...}` | 密钥注入 |
| `MODEL_MASTER_KEY_FILE` | `/run/secrets/model_master_key` | 主密钥文件 |
| `SESSION_TTL_MINUTES` | `30` | 会话空闲 |
| `CONVERSATION_WINDOW_TURNS` | `6` | 消息窗口 |
| `SQL_MAX_ROWS` | `1000` | 结果行上限 |
| `SQL_TIMEOUT_MS` | `10000` | SQL 硬超时 |
| `MODEL_TIMEOUT_MS` | `25000` | 模型超时 |

- 配置启动时校验：缺失必填项拒绝启动；弱密钥/默认密码拒绝启动。
- 不把密钥写入镜像、Git、Compose 文件或日志。
- 生产与测试使用不同数据库、不同密钥、不同域名。

### 19.5 密钥托管

- 模型密钥：数据库密文 + 主密钥文件/密钥管理服务；主密钥不进数据库。
- 数据库密码：Docker secrets 或部署环境变量注入；不写入 Compose 明文。
- 备份加密密钥：独立托管；与主密钥分离。
- 轮换：应用密钥、数据库密码、模型密钥分别有轮换流程；轮换需审计与回滚方案。

### 19.6 健康检查与资源

| 服务 | 健康检查 | 资源建议（起点） |
| --- | --- | --- |
| nginx | `nginx -t` + 443 探活 | 0.5 CPU / 256 MB |
| api | `/healthz`（不查业务库） | 2 CPU / 2 GB |
| worker | `celery inspect ping` | 4 CPU / 4 GB |
| mysql | `mysqladmin ping` | 4 CPU / 8 GB / SSD |
| redis | `redis-cli ping` | 1 CPU / 1 GB |

- 资源值是评审起点，不是容量承诺；按压测与生产监控调整。
- 容器非 root、只读根文件系统（可写卷单独挂载）、`no-new-privileges`。
- 日志轮转：Docker `json-file` 限制大小/数量，或接日志驱动。

---

## 20. 备份恢复、版本发布、数据结构升级与回滚

### 20.1 备份范围

| 类别 | 是否备份 | 说明 |
| --- | --- | --- |
| 用户/部门/角色/模板/例外 | 是 | 含权限关系 |
| 权限纪元 | 是 | 恢复后保持一致 |
| 元数据/术语/指标/主题 | 是 | 含版本与发布状态 |
| 会话/任务 | 是（应用库） | 恢复后不自动重跑 |
| 历史/审计 | 是 | 历史与审计分开保留 |
| 快照/导出文件 | 按 DEC-19 | 可排除临时文件；排除需明示 |
| 模型配置密文 | 是 | 主密钥单独托管 |
| 主密钥 | 独立托管 | 不与备份同处 |
| 业务库 | 否 | 由 DBA 既有备份负责 |

### 20.2 备份流程

```text
1. 应用库一致性导出（mysqldump --single-transaction）
2. 生成 manifest（版本、时间、表清单、行数、sha256）
3. 打包快照/导出文件（若纳入）
4. 加密（age/GPG，公钥在备份端）
5. 上传受控独立位置
6. 校验可读性与哈希
7. 记录 backup_result 审计与指标
```

示例命令（设计示例，不含真实路径/密钥）：

```bash
mysqldump --single-transaction --quick --routines --triggers --events \
  --set-gtid-purged=OFF chatbi | gzip -9 | age -r "$BACKUP_RECIPIENT" \
  > "chatbi-$(date -u +%Y%m%dT%H%M%SZ).sql.gz.age"
```

- 备份失败告警；连续失败升级。
- 备份文件权限最小化；下载/解密需双人授权（建议）。
- 频率、保留、异地副本、RPO/RTO 属 DEC-19。

### 20.3 恢复流程

```text
1. 选择已验证备份与对应主密钥版本
2. 在隔离环境启动空应用库
3. 导入 SQL；恢复文件卷
4. 运行 Alembic 校验版本
5. 校验用户/权限/元数据/指标/历史/审计数量与抽样
6. 重建 Redis 会话（可选：强制重新登录）
7. 将运行中任务标记为未完成，不自动重跑
8. 校验共享/导出入口的撤销状态
9. 开放内网访问；观察错误率
```

- 恢复后必须强制重新登录（会话不恢复），避免旧会话复活。
- 旧任务不自动重跑；历史结果标记“历史”。
- 已删除/已撤销对象不得从旧备份复活为可访问入口；恢复后重新应用撤销清单（DEC-19）。

### 20.4 发布与回滚

| 步骤 | 动作 | 回滚 |
| --- | --- | --- |
| 1 | 构建镜像，打版本 tag | 保留上一 tag |
| 2 | 备份应用库 | 备份文件 |
| 3 | 运行向前兼容迁移（expand） | 应用回滚不改库 |
| 4 | 启动新容器，健康检查 | `docker compose up` 上一 tag |
| 5 | 冒烟：登录、问数、历史、导出 | 回滚镜像 |
| 6 | 观察 30 分钟指标 | 回滚 |
| 7 | 后续版本再收缩旧字段（contract） | 需备份 |

- 迁移遵循 expand/contract：先加字段/表，双写/回填，再切换读，最后删旧；不在同一版本做破坏性变更。
- 回滚不保证数据回滚；涉及数据修复需单独脚本与备份。
- 镜像、配置、迁移版本必须可追溯；发布记录写审计。

### 20.5 数据迁移规则

1. 所有迁移经 Alembic 管理，禁止手工改生产表结构。
2. 迁移必须可重复执行（幂等）或有明确版本门禁。
3. 大表变更评估锁表时间；必要时在线 DDL 或分批回填。
4. 迁移前后校验行数、关键约束、索引。
5. 破坏性变更（删表/删列/改类型）必须单独评审 + 备份 + 回滚脚本。

### 20.6 灾难场景

| 场景 | 恢复目标 | 说明 |
| --- | --- | --- |
| 应用容器损坏 | 分钟级 | 重建容器，数据卷保留 |
| 应用库损坏 | 小时级 | 从备份恢复；RPO 取决于备份频率 |
| 文件卷损坏 | 小时级 | 快照/导出可能丢失；历史摘要仍在 |
| 主密钥丢失 | 不可恢复模型密钥 | 需重新录入密钥；备份密文不可用 |
| 业务库故障 | 依赖 DBA | 应用不承担业务库恢复 |
| Redis 丢失 | 会话失效 | 强制重新登录；任务状态在 MySQL |

---

## 21. 测试矩阵与验收追踪

### 21.1 测试分层

| 层次 | 工具 | 覆盖 | 运行时机 |
| --- | --- | --- | --- |
| 单元 | pytest | 权限合成、补丁、SQL Gate、脱敏、预算、错误映射 | 每次提交 |
| 集成 | pytest + Testcontainers（MySQL/Redis） | 仓储、任务领取、租约、Outbox、迁移 | 每次合并 |
| 契约 | Schemathesis/OpenAPI 校验 | API 字段、错误码、幂等 | 每次合并 |
| 安全 | pytest 安全集 + sqlglot 黄金用例 | 越权、注入、系统表、函数、行范围 | 每次合并 + 发布前 |
| 端到端 | Playwright | 登录、问数、追问、取消、历史、共享、导出 | 每日/发布前 |
| 性能 | k6/Locust | 5–10 秒目标、并发、队列、超时 | 发布前/季度 |
| 故障注入 | toxiproxy/脚本 | 模型超时、DB 断连、Redis 丢失、worker 崩溃 | 发布前 |
| 恢复 | 备份恢复演练 | 应用库、文件、主密钥 | 发布前/季度 |

### 21.2 安全回归集

必须覆盖：

1. SQL 注入：字符串拼接、注释、反引号、Unicode 同形字、大小写混用。
2. 系统表：`information_schema`、`mysql`、`performance_schema`、`sys`。
3. 文件/外传：`INTO OUTFILE`、`LOAD_FILE`、`LOAD DATA`。
4. 危险函数：`SLEEP`、`BENCHMARK`、`GET_LOCK`、`RELEASE_LOCK`。
5. 多语句/写操作/DDL/事务/锁。
6. 行范围：别名、JOIN、LEFT JOIN、子查询、CTE、UNION、自连接、聚合、`SELECT *`。
7. 字段用途：无 `FILTER` 却用于 WHERE；无 `GROUP` 却分组；无 `VIEW_RAW` 却导出原值。
8. 权限变更：排队/执行/发布/历史/共享/下载六个时点。
9. 对象枚举：猜历史 ID、共享 ID、导出 ID。
10. 云端外发：原始明细、未授权字段、小样本、密钥。

### 21.3 性能与故障注入

| 类型 | 场景 | 观察 |
| --- | --- | --- |
| 性能 | 1/5/10/20 并发常规问题 | P50/P95、阶段耗时、错误率 |
| 性能 | 复杂聚合/大时间范围 | 超时率、行数、内存 |
| 故障 | 模型 429/500/超时 | 主备切换、预算、降级 |
| 故障 | 业务库断连/慢查询 | 超时、连接隔离、错误提示 |
| 故障 | Redis 重启 | 会话失效、任务继续、Outbox 重投 |
| 故障 | worker kill -9 | 租约回收、EXECUTION_UNKNOWN、不重复 SQL |
| 故障 | API 重启 | SSE 重连、状态一致 |
| 故障 | 文件卷满 | 导出失败、问数降级 |
| 恢复 | 备份恢复 | 登录、权限、历史、审计、共享撤销状态 |

### 21.4 验收用例追踪（AT-01–AT-36）

| 用例 | 技术验证点 | 层次 |
| --- | --- | --- |
| AT-01 | 只读账号 + 只读事务 + AST 拒绝写/DDL | 安全/集成 |
| AT-02 | SQP 编译 + 外键路径 + 结果口径 | 集成/E2E |
| AT-03 | 响应契约无 SQL/原值；图表/摘要同源 | E2E |
| AT-04 | 指标歧义 → 澄清；不执行 SQL | 单元/E2E |
| AT-05 | 窗口 N；历史不删；结构化状态注入 | 单元/集成 |
| AT-06 | `append_dimension` 补丁 + 重新授权 | 单元/E2E |
| AT-07 | `replace_time` / `remove` 补丁；权限谓词不可删 | 单元/安全 |
| AT-08 | 成功基准选择；失败候选不覆盖 | 单元/集成 |
| AT-09 | 取消状态机；重复取消幂等；物理状态分开 | 集成/故障 |
| AT-10 | 可重试分类；安全拒绝不重试；预算共享 | 集成/故障 |
| AT-11 | 用户创建/唯一约束/禁用会话失效 | 集成/E2E |
| AT-12 | 模板+例外合成；冲突拒绝；审计 | 单元/集成 |
| AT-13 | 两部门 + 别名/JOIN/子查询/UNION/CTE | 安全 |
| AT-14 | 伪造身份字段被忽略；服务端范围 | 安全 |
| AT-15 | 掩码/禁止原值/导出拦截 | 安全/E2E |
| AT-16 | 六个检查点撤权；旧结果丢弃 | 集成/安全 |
| AT-17 | 历史保存/查看/删除；审计独立 | 集成/E2E |
| AT-18 | 重查新任务；当前权限；差异提示 | 集成/E2E |
| AT-19 | 共享仅指定用户；猜 ID 404 | 安全/E2E |
| AT-20 | 快照范围证明；不足拒绝 | 单元/安全 |
| AT-21 | 重查模式使用接收者权限；撤销后拒绝 | 集成/E2E |
| AT-22 | 元数据采集/导入预览/业务说明保留 | 集成 |
| AT-23 | 术语映射/主题审核/未发布不可见 | 单元/E2E |
| AT-24 | 指标版本/临时指标/同口径 | 单元/集成 |
| AT-25 | 同步防重入/差异/STALE 阻断 | 集成 |
| AT-26 | 用途路由/熔断/切回/输出校验 | 集成/故障 |
| AT-27 | 密钥掩码/日志/备份/解密 | 安全/运维 |
| AT-28 | trace_id 贯穿；审计字段；读取授权 | 集成/E2E |
| AT-29 | 限流/并发/超时/行数/字节 | 性能/安全 |
| AT-30 | 指标/告警/聚合/去重 | 运维 |
| AT-31 | Compose/HTTPS/端口扫描 | 运维 |
| AT-32 | 备份恢复/不重跑旧任务/撤销对齐 | 运维 |
| AT-33 | 固定问题集/冷暖缓存/P50/P95 | 性能 |
| AT-34 | 出站捕获：无原始明细/凭据/小样本 | 安全 |
| AT-35 | 导出截断/掩码/公式注入/撤权/过期 | 安全/E2E |
| AT-36 | 断线/重启/主备/DB 故障/重复提交 | 故障 |

> 上表是**待执行**的验收追踪，不表示已通过。每条用例需绑定测试数据、权限快照、模型版本与证据文件。

### 21.5 需求追踪（REQ-01–REQ-43）

| 需求 | 技术落点 | 关键验证 |
| --- | --- | --- |
| REQ-01 | §4、§10、§11 | AT-01、AT-13 |
| REQ-02 | §4、§17 | AT-33 |
| REQ-03 | §6 | AT-11、AT-12 |
| REQ-04 | §7、§10 | AT-02、AT-04 |
| REQ-05 | §13、§16 | AT-03 |
| REQ-06 | §13、§18 | AT-03、AT-28 |
| REQ-07 | §8 | AT-05–AT-08 |
| REQ-08 | §8.4 | AT-05 |
| REQ-09 | §8.3 | AT-06 |
| REQ-10 | §8.3 | AT-07 |
| REQ-11 | §8.5 | AT-08 |
| REQ-12 | §9、§11 | AT-09、AT-10 |
| REQ-13 | §6.3 | AT-11 |
| REQ-14 | §6.4、§6.5 | AT-12 |
| REQ-15 | §6.6、§10.6 | AT-13、AT-14 |
| REQ-16 | §6.7、§13.3 | AT-15 |
| REQ-17 | §6.9、§10.9 | AT-14、AT-15 |
| REQ-18 | §6.8、§6.9 | AT-16 |
| REQ-19 | §14.1 | AT-17 |
| REQ-20 | §14.1 | AT-17 |
| REQ-21 | §14.1 | AT-18 |
| REQ-22 | §14.3 | AT-19 |
| REQ-23 | §14.3、§14.4 | AT-20、AT-21 |
| REQ-24 | §6.9、§14.3 | AT-16、AT-21 |
| REQ-25 | §7.1 | AT-22 |
| REQ-26 | §7.3 | AT-23 |
| REQ-27 | §7.3、§10.6 | AT-02、AT-13 |
| REQ-28 | §7.3、§10.2 | AT-24 |
| REQ-29 | §7.3 | AT-23 |
| REQ-30 | §7.1、§7.2 | AT-25 |
| REQ-31 | §12.1 | AT-26 |
| REQ-32 | §12.3 | AT-26 |
| REQ-33 | §12.4 | AT-27 |
| REQ-34 | §18.1 | AT-28 |
| REQ-35 | §11、§17 | AT-29 |
| REQ-36 | §18.3、§18.4 | AT-30 |
| REQ-37 | §19 | AT-31 |
| REQ-38 | §19.3 | AT-31 |
| REQ-39 | §20.1 | AT-32 |
| REQ-40 | §17.4 | AT-33 |
| REQ-41 | §12.6、§13.4 | AT-34 |
| REQ-42 | §21 | 全部 |
| REQ-43 | §14.5 | AT-35 |

### 21.6 测试证据包

每次发布前归档：

1. 测试环境与版本（镜像 tag、迁移版本、模型配置版本）。
2. 测试数据说明（合成/脱敏，不含真实敏感数据）。
3. 用例执行记录（通过/失败/跳过，含 trace_id）。
4. 安全测试报告（拒绝码、越权路径、修复记录）。
5. 性能报告（问题集、并发、P50/P95、阶段耗时）。
6. 故障注入记录（注入方式、观察结果、恢复时间）。
7. 备份恢复演练记录。
8. 未关闭风险与豁免审批。

文档静态检查不能替代上述证据。

---

## 22. 从零分阶段实施建议与评审门槛

### 22.1 阶段划分

| 阶段 | 目标 | 主要交付 | 退出条件 | 估算 |
| --- | --- | --- | --- | --- |
| P0 冻结与骨架 | 决策冻结、工程骨架、CI | ADR、目录、Compose、迁移基线、健康检查 | 评审通过；空服务可启动 | 1–2 周 |
| P1 身份与权限 | 登录、会话、用户/部门/角色、权限合成、纪元 | 认证、权限服务、管理页面、审计 | AT-11/12/16 通过 | 3–4 周 |
| P2 元数据与语义 | 结构采集、版本、术语、指标、主题、检索 | 同步任务、语义管理、检索服务 | AT-22–AT-25 通过 | 3–4 周 |
| P3 查询主链路 | 会话、条件、任务、模型、SQL Gate、执行 | 端到端问数、取消、重试、结果 | AT-01–AT-10、AT-13–15 通过 | 5–6 周 |
| P4 历史/共享/导出 | 历史、快照、共享、Excel、生命周期 | 相关 API/页面/清理 | AT-17–AT-21、AT-35 通过 | 3 周 |
| P5 运维与验收 | 监控、告警、备份、压测、试点 | 运行手册、恢复演练、验收报告 | AT-26–AT-34、AT-36 通过；P0 阻断关闭 | 3–4 周 |

总估算 18–23 周，按 3–4 名开发 + 1 名测试 + 兼职 DBA/安全计算；仅为排期参考，不是承诺。阶段可并行部分：前端页面可在 P1 起并行；监控可在 P3 起接入。

### 22.2 角色与职责

| 角色 | 职责 |
| --- | --- |
| 技术负责人 | 架构、ADR、SQL Gate 评审、代码质量 |
| 后端开发 | 认证/权限/任务/模型/执行/历史/导出 |
| 前端开发 | 工作台、管理页、图表、SSE |
| 测试 | 安全集、E2E、性能、故障注入 |
| DBA | 业务库账号/负载/超时/取消/执行计划 |
| 安全 | 权限模型、云端数据、密钥、审计 |
| 运维 | Compose、TLS、备份、监控、发布 |

### 22.3 评审门槛

**门槛 A：设计冻结前**

- TD-01–TD-07 已锁定；TD-08–TD-15 逐项确认或降级为 TBD。
- DEC-03/04/05/06/07/20 的 P0 项有明确结论或书面豁免。
- 数据模型、API、SQL Gate 规则通过开发/安全/DBA 评审。
- 测试矩阵与验收阈值获批。

**门槛 B：开发完成/试点前**

- 安全回归集全部通过；无未解决的高风险缺陷。
- 权限变更六检查点验证通过。
- 取消/超时/连接隔离在测试环境验证。
- 备份恢复演练通过。
- 性能达到批准阈值；未达标有明确整改计划。

**门槛 C：生产上线前**

- P0 阻断全部关闭；生产只读账号、网络白名单、负载预算由 DBA 放行。
- 模型供应商条款/区域/保留策略获批（DEC-07）。
- 监控告警、值班与回滚流程就绪。
- 有限用户试点方案与回退方案批准。

---

## 23. 待确认决策与上线阻断项

### 23.1 技术待确认

| 编号 | 事项 | 当前建议 | 影响 | 状态 |
| --- | --- | --- | --- | --- |
| TD-08 | 模型协议抽象 | OpenAI-compatible + 适配器 | 多供应商、主备 | 【推荐】 |
| TD-09 | 快照/文件存储 | 本地受控卷，后续对象存储 | 容量、备份、下载 | 【推荐】 |
| TD-10 | 部署细节 | Compose + Nginx；资源/证书/域名待定 | 上线 | 【推荐】 |
| TD-11 | 可观测性 | Prometheus + JSON 日志 | 告警、排障 | 【推荐】 |
| TD-12 | 测试栈 | pytest/Testcontainers/Playwright/k6 | 质量 | 【推荐】 |
| TD-13 | 数据访问 | SQLAlchemy 2.0 + Alembic | 事务/迁移 | 【推荐】 |
| TD-14 | API 风格 | REST + SSE | 前端/网关 | 【推荐】 |
| TD-15 | 精确版本 | 评审时锁定并生成锁文件 | 可重复构建 | 【待决策】 |

### 23.2 业务/安全待决策对技术的影响

| 编号 | 优先级 | 待决策 | 对技术设计的影响 | 当前处理 |
| --- | --- | --- | --- | --- |
| DEC-01 | P1 | 密码/锁定/会话期限 | 认证参数、Redis TTL | 配置化，默认保守值 |
| DEC-02 | P1 | 管理/权限/审计职责分离、多角色 | 权限合成、页面 | 单角色简化，多角色并集 |
| DEC-03 | P0 | 用户例外能否扩大模板 | 合成算法、审批 | 默认 `SHRINK_ONLY` |
| DEC-04 | P0 | 本人/部门字段映射、范围组合、语法白名单 | 行谓词、SQL Gate | 映射配置化；未映射拒绝 |
| DEC-05 | P0 | 撤权时运行任务/缓存/下载竞态 | 检查点、版本 | 五检查点 + 纪元 |
| DEC-06 | P0 | 敏感清单/掩码/用途/整次或部分拒绝 | 脱敏、错误码 | 整次拒绝优先；掩码可配 |
| DEC-07 | P0 | 供应商/区域/保留/摘要/小样本 | 外发、模型路由 | 最小化；未证实不外发 |
| DEC-08 | P1 | 时区/相对时间/指标口径 | 时间解析、重查 | 显式 source；歧义澄清 |
| DEC-09 | P1 | 窗口 N/状态恢复/失败候选 | 上下文、历史 | N=6 可配；失败不覆盖 |
| DEC-10 | P1 | 快照容量/期限/血缘/删除同步 | 快照、共享 | TTL 可配；UNPROVEN 禁共享 |
| DEC-11 | P1 | 超时/行数/队列/配额/预算 | 执行、限流 | 设计起点，DBA 复核 |
| DEC-12 | P1 | 驱动取消/确认时限/断线/幂等期限 | 取消、连接 | KILL + 隔离；未知不重跑 |
| DEC-13 | P1 | 图表/分页/缓存/流式 | 结果、前端 | 规则图表；SSE |
| DEC-14 | P1 | Excel 格式/权限/额度/期限 | 导出 | 受控结果；TTL |
| DEC-15 | P1 | 主备阈值/切回/白名单/密钥 | 模型网关 | 熔断 + 人工切回 |
| DEC-16 | P1 | 导入格式/模板/覆盖/原子性 | 元数据导入 | 预览 + 整批 |
| DEC-17 | P1 | 无外键关联/指标版本/同步时刻 | 语义层 | 不猜关系；版本化 |
| DEC-18 | P1 | 审计期限/访问/失败策略/告警渠道 | 审计、告警 | 关键事件失败关闭 |
| DEC-19 | P1 | 备份频率/期限/主密钥/RPO/RTO | 备份恢复 | 应用全量；演练 |
| DEC-20 | P0 | 生产主库/副本/负载/网络/账号 | 执行、DBA 放行 | 未放行不接生产 |
| DEC-21 | P1 | 性能口径/部署资源/证书/回滚 | 压测、部署 | 5–10 秒目标；压测定 |
| DEC-22 | P1 | 验收问题集/阈值/试点 | 验收 | 矩阵为起点 |

### 23.3 P0 上线阻断项

1. DEC-03：用户例外合成规则未定 → 权限可能被扩大或冲突。
2. DEC-04：行范围映射、范围组合、语法白名单未定 → 无法证明行权限完整。
3. DEC-05：撤权竞态与生效时点未定 → 运行中任务/下载可能沿用旧权限。
4. DEC-06：敏感字段清单/掩码/用途未定 → 脱敏与导出无法验收。
5. DEC-07：云端供应商/区域/保留/摘要规则未定 → 可能违反数据边界。
6. DEC-20：生产库接入、负载、网络、账号未由 DBA 放行 → 不得接生产。

以上任一项未关闭，不得开放生产查询；可在合成数据环境开发与测试。

### 23.4 变更控制

- 技术决策变更走 ADR：背景、选项、决定、代价、影响、回滚。
- 安全相关变更（SQL Gate、权限合成、脱敏、取消）需双人评审 + 安全回归。
- 接口破坏性变更需版本化与前端同步。
- 数据库迁移遵循 expand/contract；破坏性变更单独评审。
- 文档版本与代码版本、镜像 tag、迁移版本、模型配置版本一并记录。

---

## 附录 A：关键接口签名（设计示例）

```python
from typing import Protocol, Sequence
from dataclasses import dataclass


class PermissionService(Protocol):
    def effective(self, user_id: str, epoch: int) -> "EffectivePermission": ...
    def current_epoch(self) -> int: ...
    def scope_for(self, user_id: str, table_id: str) -> "ScopeMapping": ...


class SqlGate(Protocol):
    def compile_plan(self, plan: "QueryPlan", ctx: "GateContext") -> "ValidatedSql": ...
    def validate_sql(self, sql: str, ctx: "GateContext") -> "ValidatedSql": ...


class ModelGateway(Protocol):
    def chat(self, purpose: str, payload: "ModelPayload", budget: "Budget") -> "ModelResponse": ...


class SqlExecutor(Protocol):
    def execute(self, sql: "ValidatedSql", budget: "Budget",
                cancel_token: "CancelToken") -> "RawResult": ...
    def cancel(self, attempt_id: str) -> "PhysicalCancelState": ...


@dataclass(frozen=True)
class ValidatedSql:
    sql: str
    params: Sequence[object]
    tables_used: Sequence[str]
    columns_used: Sequence[str]
    plan_hash: str
    estimated_cost: float | None
```

- `compile_plan` 与 `validate_sql` 共享同一套检查；不允许只实现其中一条。
- `ValidatedSql` 一旦生成不可修改；执行器不得再拼接 SQL。
- `CancelToken` 由任务层创建，执行器按 token 检查取消状态。

---

## 附录 B：文档自检记录

### B.1 依据文件哈希（编写前复核）

| 文件 | SHA-256 |
| --- | --- |
| `ChatBI功能设计文档_v1.0.md` | `A396DBAD1B90ABD6B604680B74EF267402EB0F72BECE3D61D43EFCAF854ED9FA` |
| `ChatBI项目设计文档_v1.0.md`（编写时名 `_初稿_v0.1.md`） | `24C0384B5AFEAD596BB7D5854546E60D0205BB75C0763A37E6C22EC8867C07D5` |

与编写计划记录一致，未发现源文档变更。

### B.2 grill 决策记录

| 轮次 | 决策 |
| --- | --- |
| Q1 | Python 3.12 + FastAPI |
| Q2 | MySQL 8.0+ 应用库 |
| Q3 | Celery + Redis；MySQL 任务表权威，Celery 仅分发 |
| Q4 | 语义层 + sqlglot AST 校验改写 |
| Q5 | 服务端会话 + HttpOnly Cookie |
| Q6 | Vue 3 + TS + Vite + Element Plus + ECharts |
| Q7 | Celery broker 用 Redis |

### B.3 静态检查

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| Markdown 标题层级 | 通过（静态） | 182 个标题，未发现 `#` 跳级 |
| 表格列数 | 通过（静态） | 未发现列数与表头不一致 |
| 代码围栏 | 通过（静态） | 100 个围栏标记，成对 |
| 内部引用 | 通过（静态） | 48 个 `§x` 引用，均能解析到标题 |
| JSON/YAML 示例 | 通过（静态） | 9 个 json/yaml 代码块均可被解析器读取 |
| REQ/AT 覆盖 | 通过（静态计数） | REQ 43/43 行、AT 36/36 行存在；语义覆盖仍需评审 |
| 敏感信息 | 通过（静态扫描） | 未发现真实 IP、镜像仓库地址、密码或 API Key 模式 |

> 以上只是文档静态检查，不替代 SQL Gate 单测、接口契约测试、端到端测试、性能压测、故障注入或备份恢复演练。

---

## 附录 C：与功能设计文档的差异与保留项

1. 本文把功能文档的“暂定方案”细化为技术实现，但不把任何暂定业务规则升级为已确认。
2. 本文新增 TD-01–TD-15 技术决策编号；与 REQ/DEC 编号并行，不替代。
3. 本文对“用户例外可扩大模板”“行范围组合”“云端摘要规则”等保持 DEC 原编号，不擅自定案。
4. 本文不引用现有代码；因此不提供代码迁移、复用或差距分析。
5. 本文的容量、超时、并发、TTL 均为设计起点，必须由压测、DBA 与业务评审确认。

---

*文档结束。*





