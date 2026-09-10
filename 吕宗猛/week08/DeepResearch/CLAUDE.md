# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目状态

「深度研究助手」综合案例（week08）。目前仓库只有 `README.md`，代码尚未开始。`README.md` 里有博查（Bocha）搜索 API 的 curl 示例，其 API Key 是课程共享密钥——不要把它写进代码或提交到仓库，运行时统一放服务端配置文件。

## 业务背景

输入一个研究主题 → 自动检索、阅读、迭代、综合 → 产出带来源引用的结构化研究报告。区别于一次性问答，核心是「规划 → 多轮检索 → 阅读抽取 → 判断补检 → 综合」的迭代研究循环。

## 已锁定的设计决策（实现前必须遵守）

### 技术栈
- **后端**：FastAPI + SQLite（单文件 `.db`），托管静态文件
- **前端**：单页 `index.html` + 原生 JS，**免构建**（不用 Vite/React 工程）
- **实时推送**：SSE（`/api/research/{task_id}/events`）；`EventSource` 不能带 header，token 走 `?token=` 查询参数
- 左侧菜单布局：研究（首页）、研究历史、模型管理、登录

### SQLite 表
`users`（bcrypt 密码哈希）、`tasks`、`events`（研究过程全落库，带 seq，支持 SSE 断线重连按 Last-Event-ID 补发 + 历史重放）、`reports`（report_md + sources JSON + meta JSON）、`models`（用户自定义 LLM）

### 认证
- JWT（7 天过期）存前端 localStorage；bcrypt 存密码；启动时种子 `admin` 账号
- 模型 API Key 用 AES-GCM 对称加密落库，密钥放 `.env` 的 `ENCRYPTION_KEY`；接口展示脱敏（如 `sk-****c72`），完整 key 永不下发前端
- 模型按 `user_id` 隔离；每用户至多一个默认模型，覆盖时前端弹确认

### 模型管理（OpenAI 兼容接口）
- 用户自定义 base_url / api_key / model_name，OpenAI SDK 调用
- 健康检测三条：**不做自动轮询**——①添加时"测试连接"（ping，max_tokens=1，10s 超时）②列表显示徽标（ok/fail/未检测）+ 手动重检按钮 ③研究任务运行前对所用模型探活一次，失败直接 error 终止
- 用户一个模型都没配时，提交研究直接报错引导去模型页，**没有服务端兜底模型**

### 研究循环（固定 pipeline，不是 agent 工具循环）
任何 chat 模型都能跑（不依赖 tool calling）。5 类 LLM 调用，各自独立、强制 JSON 输出（解析失败重试一次）：
1. **规划**：主题 → 3~5 个子问题
2. **检索**：不走 LLM，代码用子问题（+ 补检词）调 Bocha API（`summary=true`）
3. **抽取**：逐页并行，一页一调用 → `{relevance, facts: [{statement, quote, source_url}], gaps}`；**抽取输入 = Bocha 摘要，不抓网页正文**（抓取正文是后续可选扩展，抽取逻辑只认"文本 + URL"以便将来换内容源）
4. **判断补检**：全量 facts + gaps → `{sufficient, followup_queries}`，补检词喂给下一轮
5. **综合报告**：Markdown + `[n]` 引用编号（可反查来源 URL）+ "模型推断"标注无来源结论

### 轮次与置信度
- **最大轮次是页面配置项（任务级），全模块共用**；每轮 = 检索 → 抽取 → 判断。达到上限后不再调用任何模块，直接进综合
- 因轮次上限终止时，报告的"遗留问题"章节必须显式说明"已达到最大轮次 N，未继续补检"
- 置信度按来源数：≥2 独立来源=高、单来源=中、无来源=低且标注"模型推断"；报告头部注明信息截止时间（本次检索时间）
- 任务级模型下拉选择，默认选中该用户的默认模型；报告 meta 记录所用模型

## 实现顺序

建表 → 认证（JWT/登录页）→ 模型管理（加密/脱敏/健康检测）→ 研究 pipeline（5 类调用 + events 落库）→ SSE 事件流 → 前端页面
