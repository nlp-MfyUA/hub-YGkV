# 综合案例 02 · 深度研究助手

## 运行与使用说明

### 启动

```bash
pip install -r requirements.txt
# 复制 .env.example 为 .env，填写：
#   ENCRYPTION_KEY  32 位以上随机串（AES-GCM 加密模型 API Key 用）
#   JWT_SECRET      随机串
#   BOCHA_API_KEY   课程共享的博查密钥（见下方 curl 示例，只放 .env，不写进代码/前端）
python main.py        # http://localhost:8000
```

- 登录：**admin / admin123**（启动时自动种子账号）
- 流程：模型管理页添加 OpenAI 兼容模型（添加时自动测试连接，ping + 10s 超时）→ 研究页填主题、选模型、设最大轮次 → 开始研究
- 左侧菜单：研究（首页）/ 研究历史 / 模型管理 / 登录页（未登录时）
- 研究过程通过 SSE 实时推送（`/api/research/{task_id}/events`，token 走 `?token=` 查询参数），events 全程落库，断线按 Last-Event-ID 补发，历史可重放
- 轮次 = 检索 → 抽取 → 判断补检 的迭代次数（任务级配置）；达到上限后不再补检，直接综合，报告「遗留问题」章节会显式说明
- 没有任何模型时提交研究会直接报错引导去模型页，**没有服务端兜底模型**

### 代码结构

| 文件 | 职责 |
| --- | --- |
| `main.py` | 入口：加载 .env、建表、种子 admin、启动 uvicorn |
| `db.py` | SQLite（单文件 app.db）：users / tasks / events / reports / models |
| `auth.py` | JWT（7 天）+ bcrypt + 种子账号 |
| `keyciphers.py` | API Key 的 AES-GCM 加密 / 脱敏展示 |
| `bocha.py` | 博查 web-search 封装（summary=true） |
| `llm.py` | OpenAI 兼容调用：强制 JSON（失败重试一次）+ 健康检测 |
| `pipeline.py` | 研究循环：规划 → 检索 → 抽取 → 判断 → 综合，events 落库 + 实时广播 |
| `api.py` | FastAPI 路由 + SSE + 静态托管 |
| `static/index.html` | 单页前端（原生 JS，免构建） |

**业务背景**：市场 / 产品同学经常要对一个主题做调研（竞品分析、行业趋势、技术选型、政策解读）。人工搜索几十个网页、整理资料、写报告，一个主题动辄 2~3 小时，还容易漏信息、来源不可追溯。希望有一个工具能自动完成**深度研究**：输入一个主题，自动检索、阅读、迭代、综合，最终产出一份带来源引用的研究报告。

**产品定位**：「深度研究助手」——输入一个研究主题，输出：

1. 一份**结构化研究报告**（摘要、分节正文、关键结论、遗留问题）
2. **来源列表**（每条结论关联 URL / 标题 / 来源，可追溯）
3. **研究过程记录**（检索了哪些关键词、读了哪些页面、迭代了几轮）
4. **置信度说明**（结论的可靠程度、信息截止时间、无来源结论标注为"模型推断"）

**核心流程**（区别于一次性问答）：规划（拆子问题）→ 多轮检索 → 阅读抽取 → 判断是否需要补检 → 综合生成报告。

# 搜索工具

https://bocha-ai.feishu.cn/wiki/RXEOw02rFiwzGSkd9mUcqoeAnNK

```
curl -X POST "https://api.bocha.cn/v1/web-search" \
  -H "Authorization: Bearer sk-3d2293ad83aa4823a7c7ce8dd5ff8c72" \
  -H "Content-Type: application/json" \
  -d '{"query":"天空为什么是蓝色的？","summary":true,"count":10}'
```