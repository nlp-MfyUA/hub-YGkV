# CLAUDE.md

本文件供 Claude Code 在此项目中工作时参考（源自 `README.md`）。

## 项目是什么

第 8 周综合案例 h2 · **深度研究助手（Deep Research Agent）**。

业务背景：市场 / 产品同学常需对主题做调研（竞品分析、行业趋势、技术选型、政策解读）。人工检索几十个网页再整理写报告，单主题耗时 2~3 小时且易漏信息、来源不可追溯。本项目构建一个能**自动完成深度研究**的工具：输入一个主题 → 自动检索、阅读、迭代、综合 → 产出带来源引用的研究报告。

核心定位：**区别一次性问答**，强调有规划、可迭代、来源可追溯的研究闭环。

## 产品输入与输出

输入：一个研究主题（一句话即可）。

输出四项交付物：

1. **结构化研究报告** —— 摘要、分节正文、关键结论、遗留问题
2. **来源列表** —— 每条结论关联 URL / 标题 / 来源，可追溯
3. **研究过程记录** —— 检索过的关键词、读过的页面、迭代轮数
4. **置信度说明** —— 结论可靠程度、信息截止时间；无来源结论需标注为「模型推断」

## 核心流程

规划（拆解子问题）→ 多轮检索 → 阅读抽取 → 判断是否需要补检 → 综合生成报告。

实现时把「规划 / 检索 / 阅读 / 判断补检 / 综合」分别落为角色 agent（keyword / summary / judge / report），由编排器按轮次显式驱动（对应过程记录中的迭代轮数，详见「关键实现决策」）。

## 外部依赖

使用博查（Bocha）网页搜索 API 作为检索后端。

- 文档：https://bocha-ai.feishu.cn/wiki/RXEOw02rFiwzGSkd9mUcqoeAnNK

调用示例（POST）：

```
curl -X POST "https://api.bocha.cn/v1/web-search" \
  -H "Authorization: Bearer sk-3d2293ad83aa4823a7c7ce8dd5ff8c72" \
  -H "Content-Type: application/json" \
  -d '{"query":"天空为什么是蓝色的？","summary":true,"count":10}'
```

注意：

- 请求头需带 `Authorization: Bearer <API Key>`，当前 README 内嵌了一个 Key，属演示用明文密钥 —— 若用于真实交付建议改为环境变量 / 配置文件读取，避免硬编码外泄。
- `summary: true` 让接口返回摘要，可用于「阅读抽取」；`count` 控制每轮返回条数，用于控制检索深度。

## 关键实现决策（最优解 · 改动前先读）

本作业采用**确定性编排 + 角色化单步调用**，即「编排器控制循环、LLM 只扮演各角色」，**不是**让模型自治地循环调用工具。理由与取舍如下。

### 1. 架构：编排器与 agent 分离（参考综合案例-02 的做法）

- **编排器（orchestrator/engine）不是 agent**：它不参与任何一次 LLM 调用，只做**确定性控制流**——规划 → 逐关键词检索 → 总结累积 → 判断补检 → 直到「足够」或 `max_rounds` 上限 → 综合出报告。循环轮数、过程记录、来源去重、置信度计算都由代码显式完成，保证可收敛、可记录、可复现。
- **角色 agent = 无工具的单步 LLM 调用**：keyword（规划关键词）/ summary（把一轮搜索结果总结成一段正文，累积进草稿）/ judge（基于已累积草稿判断是否补检，并给新关键词）/ report（生成结构化报告 + HTML）。每个角色都是一次「提示词 + 单次调用」，不直接调搜索、不自己循环。
- **为什么这样最优**：README 的四项交付物（结构化报告 / 来源列表 / 研究过程 / 置信度）都要求**可追溯、可收敛、可审计**。确定性编排让迭代轮数、检索关键词、已读页面、来源去重都由代码逐步累积，天然满足「过程记录」；agent 无工具则不会空转，成本与轮数可被 `max_rounds` 兜底。若反过来做成模型自治的工具循环，内部轮次是黑盒、过程难记录、归因与置信度易失控。

### 2. 交互结构（沿用当前骨架）

```
规划（KeywordAgent）
  → 多轮循环：
      对每个关键词 web_search（Bocha，直接调用）
      → SummaryAgent 总结成一段正文，直接累积进报告草稿 draft
      → 收集来源（按 URL 去重）+ 记录已读页面
      → JudgeAgent 基于累积草稿判断：不足 → 用新关键词进下一轮
  → 直到 sufficient 或到达 max_rounds（默认 3）
  → 确定性计算置信度 + ReportAgent 生成结构化报告（元信息 + 草稿映射正文）与 HTML
```

- **正文分节 = 草稿段落直接映射**（heading=关键词、body=每段总结），不交给 LLM 重新组织正文，保证正文与来源一一对应。
- **搜索工具**（Bocha `web_search`）是**普通 async 函数**，返回解析后的 `list[dict]`（title/url/snippet/site_name/date），由编排器直接调用；**不**注册成 agent 的工具。
- **中间结果落盘**：每完成一轮（含规划）通过 `on_progress` 回调把当前 `process / draft / sources` 快照写盘（status 保持 running），轮询可实时看到过程；任何异常也保留已写盘的中间结果。
- **无来源结论标注**：由代码按「是否关联了来源」确定性判定并标注「模型推断」，不靠 LLM 事后补标。

### 3. 结构化输出：不用 agents SDK 的 output_type

- 参考综合案例-02 用的是 `agents` SDK + `Runner.run`。SDK 本身可用，但它带来的 `output_type` 结构化输出 **DeepSeek 不支持**，实际仍要走「提示词要求输出 JSON + 代码侧解析」。
- **最优解**：不引入 agent 框架，直接以 base model（`deepseek-v4-flash`）按 OpenAI 兼容 chat_completions 接口发起单次调用；提示词要求模型输出**唯一 JSON**（可包 ```` ```json ```` 代码块），代码侧 `parse_json` 用 pydantic 直接解析 + fence 正则兜底。SummaryAgent 例外：输出纯正文文字，不走 JSON。
- **SDK 全局初始化放模块级**（`set_default_openai_api("chat_completions")`、`set_tracing_disabled(True)`）；绝不在 async 上下文用 `run_sync`。
- **DeepSeek 空输出重试**：偶发返回 200 但 `content` 为空（与超时无关），对空输出自动重试 `LLM_RETRIES` 次（默认 3，每次退避 1s）。

## 开发 / 验证要点

- 仓库为按周提交的家庭作业结构（`week08/h2` 等），本周另有 h1 的 MCP / Skill / Hook 分支，h2 为综合应用案例。
- 目录结构已按「关键实现决策」搭好骨架（`main.py` + `deep_research/` 各模块 + `outputs/`），但各 `.py` 目前仅有 docstring、尚未实现 —— 从骨架逐个填充实现。
- 验收口径建议对照「核心流程」与「四项交付物」：能跑通一次主题 → 完整报告的闭环，且报告中来源与置信度标注规范。
- 报告输出建议结构化（Markdown / HTML / JSON 多份），便于「研究报告 / 来源列表 / 过程记录 / 置信度」独立检查。
- 参考实现（对齐架构用，勿整段照抄）：`/Users/zhanglei/zl/vscode/ai/review/week08/week08/Part2-VibeCoding实操/综合案例-02`。
