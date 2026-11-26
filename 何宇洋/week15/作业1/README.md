# 作业1：情感识别与回应

本目录包含两个可独立运行的版本，使用相同的 HTTP 协议、网页和四进程结构。LLM 使用 DeepSeek，密钥仅从 `DEEPSEEK_API_KEY` 环境变量读取。

## 1. 环境与运行

在 PowerShell 中，从本目录执行：

```powershell
conda activate python-learning
python -m pip install -r requirements.txt
# 检查变量是否存在，不显示密钥
Test-Path Env:DEEPSEEK_API_KEY
```

启动 LangGraph 版本：

```powershell
python run.py --framework langgraph
```

浏览器打开 <http://localhost:8000>，等待 <http://localhost:8000/health> 返回 `ok` 后使用。

另开终端启动 OpenAI Agents 版本，使用另一组端口：

```powershell
conda activate python-learning
python run.py --framework openai-agents --base-port 8100
```

浏览器打开 <http://localhost:8100>。两个版本都可以按 `Ctrl+C` 停止整组进程。启动器会检查密钥、端口占用，并在子进程意外退出时关闭其他进程。

## 2. 进程与接口

| 角色 | 默认端口 | 职责 | 接口 |
| --- | --- | --- | --- |
| 前端进程 | 8000 | 提供输入网页，同源代理后端请求 | `GET /`、`POST /api/chat` |
| 后端进程 | 8001 | 接收输入，串联进程1与进程2 | `POST /api/chat` |
| 进程1 | 8002 | 调用模型识别情感，输出标签与依据 | `POST /classify` |
| 进程2 | 8003 | 根据已识别情感生成鼓励或排解回应 | `POST /respond` |

所有进程均提供 `GET /health`；前端健康检查递归检查后端和两个工作进程，不调用付费模型。每个进程的 `/docs` 提供接口调试页面。`--base-port` 同时改变四个端口。

```text
用户 → 前端进程 → 后端进程 → 进程1：情感识别
                              ↓ 分类结果
                         进程2：positive → 鼓励
                               negative → 排解
用户 ← 前端进程 ← 后端进程 ← 回应结果
```

两个工作进程各自调用一次模型，单次用户请求通常包含两次模型请求。它们是独立 OS 进程，通过 HTTP 交换数据。浏览器中没有密钥，也不直接请求模型。

## 3. 两种框架的实现

- `langgraph_app/workflow.py`：通过 `StateGraph` 定义 `START → classify → 条件边 → encourage/comfort → END`，通过 `ainvoke` 执行。节点调用独立的识别与回应服务。`langgraph_app/engine.py` 使用 OpenAI 兼容客户端调用 DeepSeek。
- `agents_app/engine.py`：进程1使用识别 Agent，进程2持有鼓励和排解 Agent，由分类标签确定调用哪个 Agent。均通过 `Runner.run` 执行，显式使用 `OpenAIChatCompletionsModel`，关闭 OpenAI tracing。`agents_app/workflow.py` 采用确定性的代码编排，先等识别完成，再请求回应进程。
- `common/models.py`：统一请求、识别结果和回应协议，禁止空白输入，限制用户文本为 2000 字符，验证模型分类输出。格式错误返回服务错误，不默认伪造分类。
- `common/service.py`：按角色创建服务，处理上下游超时、网络故障和模型输出校验失败；应用错误消息不含上游凭证。
- `common/index.html`：输入、提交状态、情感标签、识别依据、策略、回应与错误展示；使用 `textContent` 渲染模型结果。

本作业要求二分类，因此约定平静/中性归为 positive，混合情绪中明显的痛苦归为 negative。此约定可在 `common/llm.py` 修改。本实现每条输入独立分析，不维护多轮会话。

## 4. 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无，必填 | 只读取环境变量，不自动加载 `.env` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 可按账号支持情况修改 |
| `BACKEND_URL` | `http://127.0.0.1:8001` | 单独启动服务时使用 |
| `SENTIMENT_URL` | `http://127.0.0.1:8002` | 单独启动服务时使用 |
| `RESPONSE_URL` | `http://127.0.0.1:8003` | 单独启动服务时使用 |

`run.py` 根据 `--base-port` 自动设置内部服务 URL。当前 DeepSeek 文档示例使用 `deepseek-flash`；两个版本均关闭 thinking，识别阶段采用 JSON object 输出并进行本地校验。密钥未设置、网络失败、额度不足或模型不支持时，需要检查配置和网络。

## 5. 验证

```powershell
# 本地模拟模型：启动四个真实服务进程，无需密钥，不产生模型费用
python verify.py
# 真实 DeepSeek：两个版本各测试正负两种输入，通常合计 8 次模型调用
python verify.py --live
# 仅测试一个版本
python verify.py --framework openai-agents --live
```

验证覆盖网页访问、四进程健康检查、正向鼓励、负面排解、空白/超长/缺字段/类型错误输入、回应进程停止后的故障传播。模拟模型只在验证脚本内使用，业务服务始终调用所配置的 LLM。

PowerShell 接口示例：

```powershell
$body = @{ text = '今天完成了很难的任务，很开心！' } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/chat -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

## 6. 参考文档

- [LangGraph 条件边与状态图](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [OpenAI Agents 自定义模型提供商](https://openai.github.io/openai-agents-python/models/)
- [FastAPI 生命周期](https://fastapi.tiangolo.com/advanced/events/)
- [DeepSeek API 与模型配置](https://api-docs.deepseek.com/)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
