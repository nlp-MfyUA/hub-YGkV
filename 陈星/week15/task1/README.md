# 作业 1 · 双框架情感识别与回应

LangGraph 与 OpenAI Agents SDK 各实现一套独立的四进程链路。前端使用终端交互，三个服务通过 HTTP 通信。一键启动器负责拉起进程、等待服务就绪和退出时清理。

| 进程 | 职责 | LangGraph | OpenAI Agents SDK |
| --- | --- | --- | --- |
| 前端 | 接收用户输入，展示标签、回复、执行者和四个 PID | 终端 | 终端 |
| 后端 | 接收 `POST /chat`，先调进程 1，再把原文、情感标签和理由交给进程 2 | 8000 | 8100 |
| 进程 1 | `POST /analyze` 返回 `positive` / `negative`、依据和置信度参考值 | 8001 · 单节点 `StateGraph` | 8101 · `Agent` + `Runner.run`，`output_type=SentimentResult` |
| 进程 2 | `POST /respond`，正向鼓励、负面排解 | 8002 · `add_conditional_edges` 根据状态选节点 | 8102 · Python 从标签选目标，SDK 执行 Handoff 并核对接手者 |

## 安装与启动

使用 Python 3.12，在解压后的 `homework1` 目录执行。

```bash
python -m venv .venv
```

macOS / Linux 激活环境用 `source .venv/bin/activate`。Windows PowerShell 用 `.\.venv\Scripts\Activate.ps1`。然后执行：

```bash
python -m pip install -r requirements.txt
python -m langgraph_impl.run_all
```

输入“今天好开心，面试通过了！”验证鼓励，再输入“今天我很焦虑，担心明天的面试。”验证排解。输入“退出”结束。启动另一套时执行：

```bash
python -m openai_agents_impl.run_all
```

也可以用单次模式，执行一条输入后自动结束：

```bash
python -m langgraph_impl.run_all --text "今天好开心，面试通过了！"
python -m openai_agents_impl.run_all --text "今天我很焦虑，担心明天的面试。"
```

如果要观察进程之间的 HTTP 请求，用四个终端分别执行 `python -m langgraph_impl.process1_sentiment`、`python -m langgraph_impl.process2_responder`、`python -m langgraph_impl.backend` 和 `python -m langgraph_impl.frontend`。OpenAI Agents SDK 版把模块前缀换成 `openai_agents_impl`。三个服务都提供 `GET /health` 和 `/docs`。

## 模型模式

- `mock` 是默认模式。初次安装完成后可离线运行，两套依旧执行真实的 LangGraph 图或 Agents SDK 的 Runner 和 Handoff。分类用固定词表，回复用模板。未命中的输入按二分类演示约定以较低参考值走鼓励分支。词表无法可靠理解反讽、复杂否定或上下文，置信度是演示参考值。
- `openai` 调用配置的模型。将 `.env.example` 复制为 `.env`，填写 `OPENAI_API_KEY`，并设置 `LLM_MODE=openai`。系统环境变量优先。可选 `auto` 在存在 API Key 时使用真实模型。
- OpenAI Agents SDK 版进程 1 需要 JSON Schema 结构化输出，进程 2 需要工具调用并支持 `tool_choice=required`。使用第三方兼容网关时须单独确认这两项能力。LangGraph 版进程 1 要求模型输出 JSON，并在本地校验。模型出错会作为失败返回。

## 验证

```bash
python -m pytest -q
```

测试用 Mock 模式启动真实服务进程，检查正负分支、接手者、四个不同的 PID 和错误处理。真实模型的输出质量与兼容性需要用实际模型验证。
