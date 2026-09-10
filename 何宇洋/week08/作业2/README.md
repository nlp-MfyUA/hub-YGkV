# 深度研究助手

**业务背景**：市场 / 产品同学经常要对一个主题做调研（竞品分析、行业趋势、技术选型、政策解读）。人工搜索几十个网页、整理资料、写报告，一个主题动辄 2~3 小时，还容易漏信息、来源不可追溯。希望有一个工具能自动完成**深度研究**：输入一个主题，自动检索、阅读、迭代、综合，最终产出一份带来源引用的研究报告。

**产品定位**：「深度研究助手」——输入一个研究主题，输出：

1. 一份**结构化研究报告**（摘要、分节正文、关键结论、遗留问题）
2. **来源列表**（每条结论关联 URL / 标题 / 来源，可追溯）
3. **研究过程记录**（检索了哪些关键词、读了哪些页面、迭代了几轮）
4. **置信度说明**（结论的可靠程度、信息截止时间、无来源结论标注为"模型推断"）

**核心流程**（区别于一次性问答）：规划（拆子问题）→ 多轮检索 → 阅读抽取 → 判断是否需要补检 → 综合生成报告。

## 首版边界

个人本地后端 API，检索中英文公开 HTML 网页，输出中文 Markdown 和 JSON。没有前端、登录、多人服务、部署、PDF 解析或文件上传。接口文档可通过 `/docs` 交互调用。

单进程、单活动任务。状态只保存在内存，产物保存在 `outputs/<任务ID>/`；重启不会恢复任务，也不能通过 API 查询以前的任务。旧报告仍可从磁盘读取。正常关闭时会保存中断说明，强制结束进程或断电无法保证保存。

## 环境与启动

在项目根目录使用 PowerShell：

```powershell
# 已有环境，无需重建；使用绝对路径可避免 conda 未加入 PATH 的问题。
& 'D:\miniconda3\envs\python-learning\python.exe' -m pip install --no-user -r requirements-dev.txt

# DEEPSEEK_API_KEY 应预先配置在本地环境变量中，启动进程时必须能够继承。
# 只检查是否存在，不显示内容：
Test-Path Env:DEEPSEEK_API_KEY

& 'D:\miniconda3\envs\python-learning\python.exe' -m uvicorn research_assistant.api:app --host 127.0.0.1 --port 8000 --workers 1
```

浏览器打开 [接口文档](http://127.0.0.1:8000/docs)。研究运行期间不要使用 `--reload`，也不要增加 worker 数量：任务状态和活动任务限制属于单进程。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无 | 必填；只从进程环境读取，不加载 `.env` 文件 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 可覆盖为 HTTPS 兼容接口，不允许内嵌凭据 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 不自动切换模型 |
| `RESEARCH_OUTPUT_DIR` | `outputs` | 相对于启动目录，也可使用绝对路径 |

设置系统或用户环境变量后，已打开的终端或桌面应用可能仍持有旧环境，需要重新打开。不要将密钥粘贴到 README、源代码或聊天中。

## API 示例

```powershell
$body = @{
    topic = 'Python 中 asyncio 与线程分别适合哪些 I/O 任务？'
    max_rounds = 2
    max_pages = 8
    timeout_seconds = 300
} | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/research' -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$id = $job.id
Invoke-RestMethod "http://127.0.0.1:8000/research/$id"
Invoke-RestMethod "http://127.0.0.1:8000/research/$id/events"

# 状态变为 completed、partial 或 failed 且 report_available=true 后下载：
Invoke-WebRequest "http://127.0.0.1:8000/research/$id/report?format=markdown" -OutFile 'report.md'
Invoke-WebRequest "http://127.0.0.1:8000/research/$id/report?format=json" -OutFile 'report.json'
```

| 接口 | 行为 |
| --- | --- |
| `GET /health` | 返回 `ready` 或 `not_ready` 及必要配置错误，不调用模型；不代表外部服务连通性检查 |
| `POST /research` | 返回 202、任务 ID 和状态 URL；缺少必要配置返回 503；已有活动任务返回 409 |
| `GET /research/{id}` | 返回阶段、轮数、成功读取数、尝试网页数、已用时间、剩余时间、token 用量和错误摘要 |
| `GET /research/{id}/events` | 返回顺序过程记录，包括计划、检索词、候选链接、页面、证据、补检判断和停止原因 |
| `GET /research/{id}/report?format=json\|markdown` | 下载报告；未生成返回 409；未知任务返回 404 |

主题去除首尾空白后须为 2–1000 字符；预算必须为整数。轮数可设 1–2、网页数 1–8、时长 10–300 秒，只允许调低，超出范围或未知字段返回 422。

任务状态：`running`（运行）、`completed`（证据评估充分且完成综合）、`partial`（有证据但预算或生成受限）、`failed`（没有有效证据或产物保存失败）。失败任务也尽量提供说明报告，不能只凭 HTTP 200 判断研究成功。

## 研究预算与输出

- 最多 3 个子问题；每轮最多 3 条查询，每条最多 5 条候选。第一轮为补检预留页面额度；相同 URL 去掉片段后去重，重定向至已读页面也不重复抽取。
- 失败的网页访问计入网页预算；同一 URL 的一次网络重试不重复计数。重定向属于该次页面访问，最多跟随 5 次，每一跳都检查目标。
- 默认总时长 300 秒，预留总时长的 20%（最多 60 秒）用于报告。预算涵盖检索、网络调用和重试；终止时清理子进程及本地写盘可能有少量额外耗时。
- 短暂错误最多重试一次；鉴权失败不重试，不静默切换模型。报告生成失败时，用已提取证据生成部分报告。
- DDGS 同步检索在可终止的子进程中执行；免费搜索可能限流或无结果。HTTPX 获取不超过 2 MiB 的 HTML，Trafilatura 抽取正文；每页最多取正文前 14000 字符，不运行 JavaScript、不绕过登录和验证码。
- 网页请求不使用系统代理，解析结果全部必须为公开 IP；连接固定到通过检查的 IP，并保留 Host 和 TLS SNI。只允许 HTTP(S) 标准端口，拒绝私网、本机和不安全重定向。
- 每条证据保存来源 ID 和逐字摘录；只有摘录能匹配实际正文才保留。报告引用由程序关联真实证据；无来源或引用无效时标记“模型推断”。这能检查引用存在和摘录匹配，不能替代语义事实核查。
- 置信度为高／中／低及理由；单一来源不足以给出高置信度。发布日期可能未知，抓取时间不能作为发布日期，也不保证内容仍然有效。

每个任务生成 `report.md`、`report.json`、`sources.json`、`events.json`。JSON 报告包含摘要、分节陈述、关键结论、遗留问题、来源冲突、证据、信息截止说明和用量。所有事实性陈述统一带有 `basis`、`citations`、`confidence` 和 `confidence_reason` 字段。

用量记录包括模型尝试次数、返回用量的调用次数、输入／输出／总 token。超时或连接中断时服务端可能已产生用量但没有返回 usage，因此本地记录不等同于最终账单；不估算货币费用。

## 验证

```powershell
# 默认测试离线，禁止真实 HTTP 传输。
& 'D:\miniconda3\envs\python-learning\python.exe' -m pytest

# 显式执行一次真实快速研究，会联网并产生 API 用量。
& 'D:\miniconda3\envs\python-learning\python.exe' scripts/verify_live.py --live
```

真实验收在进程内调用同一组 API，实际执行免费搜索、网页读取和 DeepSeek 调用，检查来源引用、报告下载和预算，并将结果写入任务目录的 `acceptance.json`。不自动追加第二次研究。

测试覆盖多轮补检、提前停止、预算耗尽、检索失败、空正文、模型输出格式错误、虚构摘录与引用、任务冲突、配置缺失、报告落盘、重启、关闭中断及网络目标检查。

## 代码结构与故障定位

`research_assistant/api.py` 管理接口与任务生命周期；`engine.py` 管理预算与研究循环；`llm.py` 封装模型；`retrieval.py` 和 `search_worker.py` 负责检索抓取；`reporting.py` 校验引用、渲染和保存报告；`models.py` 定义输入与模型响应结构。长期约束见 [AGENTS.md](AGENTS.md)。

配置缺失先检查 `/health` 和启动进程环境。研究不完整先查看任务的 `stop_reason`、`errors` 和 `/events`：403、429、DNS 错误及正文为空都会记录。遇到免费检索限制时可稍后手动创建新任务；程序不会为成功率偷偷增加预算。磁盘写入失败时任务标为失败，内存报告仍可通过 API 获取。
