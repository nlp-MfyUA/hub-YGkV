# ChatBI Agent 技术设计文档
> 文档版本：V1.0
> 配套文档：《ChatBI Agent 功能设计文档》
> 适用对象：后端、前端、算法、测试、运维
> 项目定位：面向公司内部业务人员的 Web ChatBI Agent（MVP版本）
> 核心目标：自然语言查询MySQL、NL2SQL、图表自动生成、自动分析报告、RAG检索、独立RBAC行列权限、SQL安全校验、会话收藏、审计日志、预留MCP Client扩展能力

## 1 概述
### 1.1 文档目的
基于已定功能需求，确定整套系统技术栈、架构分层、核心模块技术方案、数据存储方案、安全方案、部署方案、风险与约束，指导开发落地。

### 1.2 需求回顾（核心约束）
- 用户群体：公司内部业务人员，预估并发 100
- 业务数据源：MySQL
- 核心链路：自然语言 → RAG检索元数据 → 选表字段校验 → LLM生成SQL → SQL安全+权限校验 → 执行查询 → 图表配置生成 + 分析报告生成
- 核心特性：独立RBAC（行权限+列权限）、RAG向量检索、SQL自动重试（最多5次）、会话持久化、报表收藏、查询缓存、全链路审计日志、预留MCP Client接口
- MVP 范围限制：不做多租户、不对外网开放、不做数据脱敏、不支持报告导出

### 1.3 非功能约束
- LLM 调用超时：60s
- 单查询最大返回行数：2000行
- 查询缓存默认有效期：30min
- 元数据同步方式：定时增量同步至向量库，支持手动全量重建
- 交互输出方式：SSE 流式返回 Agent 思考、SQL、表格、图表、报告

## 2 技术栈选型
> 选型原则：开源成熟、社区活跃、上手成本低、生态匹配内部MVP场景，后期便于平滑扩展。

### 2.1 后端技术栈
- 主语言 & Web框架：**Go(Golang) + Gin**
  > 理由：高性能协程模型，适合SSE流式并发；单二进制部署简单；IO密集场景（数据库、LLM调用、向量检索）优势明显；便于统一做超时、限流控制。
- ORM：**GORM**
- SQL解析校验组件：**vitess-sqlparser**
  > 用于SQL语法解析、字段提取、高危SQL检测、列权限校验。
- 向量数据库：**Chroma**
  > 轻量、开箱即用，无需复杂集群；本项目仅存储表/字段注释元数据，数据量很小；支持向量+关键词混合检索；支持增量更新；后期可平滑迁移至 Milvus / Qdrant。
- 缓存：**Redis**
  > 用途：查询结果缓存、用户权限上下文缓存、限流、模型调用临时状态；缓存Key包含权限标识，实现权限隔离。
- 业务数据库：**MySQL 8.0**
  > 存储用户、角色、权限配置、会话、消息、收藏记录、审计日志、模型配置、元数据同步记录。
- 定时任务：**robfig/cron/v3**，用于元数据定时同步向量库。
- MCP Client SDK：官方 Go MCP SDK，封装调用框架；MVP阶段仅预留接口，暂不实现鉴权。

### 2.2 大模型接入层
- 接入方式：统一封装HTTP代理层，对接国内大模型API（通义千问、文心一言、DeepSeek等）
- 协议：优先使用 OpenAI 兼容格式，兼容厂商原生HTTP接口
- 能力：多模型配置、模型-角色绑定、统一超时控制、请求日志、失败记录
- Prompt管理：代码内维护分层Prompt模板（意图选表字段Prompt、SQL生成Prompt、图表生成Prompt、报告生成Prompt）；MVP不独立开发Prompt后台

### 2.3 前端技术栈
- 框架：**Vue3 + Vite + TypeScript**
- UI组件库：**Element Plus**
- 图表库：**ECharts**（折线、柱状、饼图等常规BI图表）
- 状态管理：Pinia
- 网络：Axios + EventSource（SSE流式接收消息）
- 路由：Vue Router，区分普通用户路由、管理员路由
- 打包：Vite打包，静态资源托管于Nginx

### 2.4 中间件汇总
| 组件 | 用途 |
| ---- | ---- |
| MySQL 8.0 | 业务主库（用户、权限、会话、收藏、审计、配置） |
| Redis | 查询缓存、权限上下文缓存 |
| Chroma | 向量库，存储MySQL元数据（表、字段注释） |
| Nginx | 前端静态资源托管、反向代理后端接口、SSE长连接转发 |

### 2.5 部署基础环境
- 运行环境：Linux（Ubuntu / CentOS）
- 容器方案：Docker + Docker Compose
> MVP 优先容器化一键拉起，简化运维；不引入K8s。

## 3 系统整体架构
分层架构：**接入层 → 网关&鉴权层 → 业务服务层 → 能力模块层 → 存储层 → 外部依赖**

前端 Vue3 页面
↓ Nginx 反向代理
API 网关 & 鉴权模块（Gin）
├─ 用户认证、token 校验
├─ 路由分发
└─ 基础限流
↓
业务服务层
├─ 用户 & RBAC 权限服务
├─ 会话 & 消息服务
├─ 收藏管理服务
├─ 审计日志服务
├─ 元数据同步服务
├─ 缓存管理服务
└─ 模型配置服务
↓
核心 Agent 能力模块
├─ RAG 检索模块（Chroma 混合检索）
├─ LLM 调度模块（多模型调用、超时控制）
├─ NL2SQL 流程模块（选表字段校验 → SQL 生成）
├─ SQL 安全 & 权限校验模块（vitess-sqlparser）
├─ MySQL 查询执行模块（自动拼接行权限条件）
├─ 图表配置生成模块
├─ 分析报告生成模块
├─ SQL 重试控制器（最多 5 次）
└─ MCP Client 封装模块（预留）
↓
存储层
├─ MySQL（业务数据）
├─ Redis（缓存）
└─ Chroma（向量）
↓
外部依赖
├─ MySQL 业务数据源（用户查询的业务库）
└─ 国内大模型 API 服务


### 3.1 主链路时序（技术视角）
1. 前端建立 EventSource SSE 连接，携带 token、会话ID、用户提问、选中模型
2. 后端鉴权，加载用户角色、行权限变量、列权限白名单，存入上下文
3. RAG模块：根据用户query做向量+关键词混合检索；**检索阶段过滤该用户无权限的表、字段**
4. LLM调用（第一步：选表、选字段、识别指标维度）
5. 元数据校验器：校验LLM输出的表名、字段是否存在于元数据快照，不存在直接拦截，规避幻觉
6. LLM调用（第二步：生成SQL语句）
7. SQL解析器（vitess-sqlparser）两层校验
   - 安全校验：拦截DDL/DML、无LIMIT、结果集超限SQL
   - 列权限校验：提取SELECT字段，对比用户白名单，非法字段直接拒绝
8. 校验通过：自动拼接WHERE行权限过滤条件
9. 执行SQL查询目标MySQL数据源，限制返回行数上限
10. 写入Redis缓存（Key携带权限标识）
11. LLM根据返回数据，输出ECharts option配置
12. LLM根据结果与原始问题生成富文本分析报告
13. SSE分段流式推送：思考文本 → SQL → 表格数据 → 图表配置 → 分析报告
14. 全流程信息异步写入审计日志表
15. 异常分支：SQL报错 → 重试控制器循环重试（最多5次），每次携带原始问题、上一轮SQL、数据库报错信息重新生成SQL；达到上限返回失败提示

## 4 核心模块详细技术设计
### 4.1 认证 & RBAC权限模块
- 认证方式：JWT Token，登录下发，有效期可配置
- 核心数据模型：user、role、user_role、table_col_permission、table_row_permission
- 列权限双层实现：
  1. RAG检索前置过滤：Chroma召回时过滤无权字段
  2. SQL解析后二次校验，提取字段和权限白名单对比兜底
- 行权限实现：
  行权限表达式预存储在 `table_row_permission`，变量 `${current_user.dept_id}` 在服务层渲染替换，拼接到SQL WHERE条件。
  > 重要：行权限表达式仅管理员配置，禁止终端用户自定义表达式，防止注入风险。
- 权限合并：用户绑定多个角色时，权限取并集。

### 4.2 元数据同步 & RAG模块
- 同步来源：目标业务MySQL的 information_schema，读取表名、表注释、字段名、字段注释、字段类型
- 同步任务：cron定时任务 + 手动触发全量同步
- 增量逻辑：对比本地元数据快照，仅将变更的表/字段更新至Chroma；已删除元数据从向量库删除
- 检索策略：Chroma向量检索 + BM25关键词混合召回；按TopN、相似度阈值过滤
- Embedding方案：复用大模型厂商Embedding接口；MVP不本地部署Embedding模型，降低运维成本
- 召回内容处理：检索到的片段全部原文送入LLM，不做摘要压缩

### 4.3 NL2SQL + SQL安全校验模块
- 解析库：vitess-sqlparser
- 校验规则：
  - 语句类型校验：仅放行SELECT；CREATE/ALTER/DROP/TRUNCATE/INSERT/UPDATE/DELETE直接拦截
  - LIMIT校验：检测是否缺少LIMIT，校验LIMIT值不超过全局上限
  - 字段提取，用于列权限校验
- 重试控制器：独立状态机，最大重试次数=5；每次重试携带原始query、上一轮SQL、MySQL原生error信息
> 用户手动编辑提交SQL，和AI生成SQL走完全相同校验链路，不存在放行白名单。

### 4.4 缓存模块（Redis）
- Cache Key 结构：`chatbi:query:{userId}:{permissionHash}:{sqlText}`
  - permissionHash：用户当前所有角色权限的哈希值；权限变更自动失效缓存
- 缓存内容：表格结果集、图表配置、报告文本
- 过期策略：TTL 30min（后台可配置）
- 黑名单机制：后台配置禁止缓存的数据表，命中黑名单表的查询不写入缓存
- 管理接口：清理单条缓存、一键清空全部缓存，供管理后台调用

### 4.5 LLM调度模块
- 抽象设计：定义统一LLM Provider接口，统一 `ChatStream()` 方法；不同厂商单独实现adapter
- 参数控制：timeout=60s；温度temperature：选表、SQL生成 0.1（低随机性，稳定优先），报告生成 0.7
- 流式透传：LLM返回流直接透传到SSE，后端减少内存缓冲
- 模型权限隔离：模型绑定角色，前端下拉框仅展示该角色允许使用的模型

### 4.6 MCP Client模块
- 定位：系统作为 MCP Client，封装基础调用框架
- MVP范围：仅实现连接、调用工具、接收结果的基础结构
- 鉴权逻辑：预留接口，一期不实现
- 角色：本系统不对外暴露MCP Server，只作为客户端调用外部MCP服务

### 4.7 会话、收藏、审计
- 会话：MySQL存储 session、message 表；消息存储结构化数据（思考内容、sql、chart_option、报告、错误信息）
- 收藏：存储 query、sql、chart_option、报告文本；**不存储明细结果**，打开收藏时重新执行查询，自动走权限校验和缓存逻辑
- 审计日志：同步写入mysql审计表；全链路信息落盘，不脱敏；后台提供分页检索接口

### 4.8 前端模块
- 聊天主页面：EventSource订阅SSE；消息卡片渲染Markdown、表格、ECharts图表
- SQL编辑：弹窗编辑SQL，提交后端校验执行
- 管理后台页面：表单维护用户、角色、权限、同步任务、RAG参数、模型配置、缓存、审计日志查询

## 5 数据库核心表设计（精简）
1. `sys_user` 用户表：id, username, password_hash, dept_id, status, create_time
2. `sys_role` 角色表：id, name, desc
3. `sys_user_role` 用户角色关联表
4. `sys_model` 大模型配置表：id, name, provider, endpoint, api_key, status
5. `sys_role_model` 角色-可使用模型关联表
6. `sys_table_col_permission` 列权限：role_id, table_name, allow_columns
7. `sys_table_row_permission` 行权限：role_id, table_name, filter_expr
8. `meta_table_field` 元数据快照：id, table_name, field_name, comment, field_type
9. `chat_session` 会话：id, user_id, title, create_time
10. `chat_message` 消息：id, session_id, role, query, llm_thought, sql, chart_option, report, error, model_name
11. `chat_favorite` 收藏：id, user_id, query, sql, chart_option, report
12. `audit_log` 审计日志：id, user_id, session_id, query, rag_chunks, select_tables_fields, sql, sql_check_result, rows, cost, error, model, create_time
13. `meta_sync_record` 元数据同步记录

## 6 安全设计
1. 认证：JWT，密码采用 bcrypt 哈希存储
2. SQL注入防护：业务查询全部使用GORM参数化查询；行权限表达式由管理员预配置，禁止用户自定义表达式
3. SQL管控：高危语句拦截、行数限制、查询超时控制
4. 权限隔离：RAG前置过滤 + SQL字段二次校验 + 行条件拼接三层隔离
5. LLM提示词注入防护：Prompt增加边界隔离标记，对用户输入做基础清洗
6. 接口权限：管理后台接口增加管理员角色校验，普通用户无法访问

## 7 部署方案（Docker Compose）
服务清单：
- chatbi-server（Go后端服务）
- chatbi-web（前端静态资源，Nginx托管）
- mysql（本系统业务库）
- redis
- chroma

> 说明：用户查询的业务MySQL数据源为外部独立数据库，不和本系统容器捆绑。

目录结构示例
chatbi/
├── docker-compose.yml
├── server/
├── web/
├── mysql/
├── redis/
└── chroma/


## 8 风险点 & 应对方案
| 风险 | 影响 | 应对方案 |
| ---- | ---- |
| LLM幻觉，选出不存在的表/字段 | 生成无效SQL | 前置元数据校验器，校验表字段真实存在才进入SQL生成环节 |
| 向量同步任务执行失败 | 元数据老旧，RAG召回错误 | 同步失败记录日志；存量向量继续可用，不阻断系统 |
| 大模型接口不稳定、超时 | 用户查询失败 | 统一60s超时；记录错误日志；一期不自动切换模型，二期补充降级逻辑 |
| 缓存串权限，不同用户拿到别人数据 | 越权风险 | Cache Key增加权限哈希，权限变化缓存隔离 |
| SSE长连接较多，协程堆积、内存上涨 | 后端服务不稳定 | Gin协程超时控制，客户端断开自动回收协程 |

## 9 二期、三期技术扩展预留
- P1（二期）：模型自动降级切换、日志归档、会话分组、报告导出PDF
- P2（三期）：MCP鉴权完整实现、接入更多MCP工具、支持Doris/StarRocks等多数据源、本地部署Embedding模型替换API调用

## 10 技术配置参数汇总
| 参数 | 默认值 |
| ---- | ---- |
| LLM调用超时 | 60s |
| SQL最大返回行数 | 2000 |
| SQL最大重试次数 | 5 |
| Redis缓存TTL | 30min |
| RAG TopN | 8 |
| RAG相似度阈值 | 0.65 |
