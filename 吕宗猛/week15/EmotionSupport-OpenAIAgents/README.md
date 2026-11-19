# 心屿 · 情感陪伴（OpenAI Agents SDK 版）

基于 OpenAI Agents SDK 的多 Agent 情绪支持演示。用户在前端输入一句话，后端先运行情感识别 Agent，再按识别结果选择正向鼓励 Agent 或负面排解 Agent。

## 一、项目定位

- 前端进程：只负责页面与用户输入，默认端口 8613。
- 页面特性：新消息与流式文字自动滚动到最底部；每轮回应结束显示绿色「回应完成」标识。
- 后端进程：接收前端请求，串联情感识别与回应 Agent，默认端口 8623。
- 多 Agent：3 个 Agent，加上中性规则兜底。
- 对话上下文：后端从 SQLite 读取最近 5 轮，超过 5 轮自动截断。
- 会话记录：本地 SQLite 持久化；每次聊天开始时由 LLM 生成会话标题。
- 模型：本地 Magpie 网关的 workbuddy/deepseek-v4.1-flash。

## 二、架构

    浏览器
      │  http://127.0.0.1:8613
      ▼
    前端进程（FastAPI + 原生 HTML/CSS/JS）
      │  /api/* 反向代理
      ▼
    后端进程（FastAPI）
      │  SQLite（data/sessions.db）
      ▼
    OpenAI Agents SDK 编排
      ├─ Runner.run(情感识别 Agent) -> EmotionResult
      ├─ 按 label 选择
      ├─ Runner.run(正向鼓励 Agent)
      ├─ Runner.run(负面排解 Agent)
      └─ 中性规则兜底（不调用第 4 个 Agent）

前端与后端是两个独立的 Python 进程，可以分别启动、分别重启。前端通过 httpx 把 /api 请求代理到后端，浏览器只需要访问 8613。

## 三、多 Agent 设计

| 序号 | Agent | 职责 | 触发条件 |
|---|---|---|---|
| 1 | 情感识别 Agent | 输出 label、confidence、intensity、reason、keywords | 每次请求 |
| 2 | 正向鼓励 Agent | 具体肯定用户的努力与感受，给出温和延伸建议 | label = positive |
| 3 | 负面排解 Agent | 先共情命名情绪，再给最小可控动作或调节练习 | label = negative |
| - | 中性规则兜底 | 用稳定模板陪用户把话说完，不额外调用模型 | label = neutral |

说明：题目要求“正向则鼓励，负面则排解”，中性输入没有明确归属，因此用规则兜底，避免为了凑分支再加一个不必要的 Agent。这样仍然是 3 个 Agent。

## 四、目录结构

    EmotionSupport-OpenAIAgents/
    ├── backend/
    │   ├── main.py              后端进程入口（FastAPI，8623）
    │   ├── config.py            Magpie、端口、历史轮数配置
    │   ├── schemas.py           ChatTurn / EmotionResult
    │   ├── pipeline.py          Runner.run 顺序编排、事件流
    │   ├── storage.py           SQLite 会话存储（sessions / messages）
    │   ├── core/llm.py          AsyncOpenAI + OpenAIChatCompletionsModel
    │   ├── agent_builders/
    │   │   ├── emotion_agent.py     情感识别 Agent 构建器
    │   │   ├── support_agents.py    正向鼓励 / 负面排解 Agent 构建器
    │   │   ├── title_agent.py       会话标题生成 Agent 构建器
    │   │   └── base.py              JSON 解析、离线模拟
    │   └── smoke.py             命令行冒烟测试
    ├── data/sessions.db          运行后自动生成的本地会话库
    ├── frontend/
    │   ├── main.py              前端进程入口（FastAPI + 静态资源 + /api 代理，8613）
    │   └── web/
    │       ├── index.html
    │       ├── model-config.html
    │       ├── model-config.js
    │       ├── style.css
    │       └── app.js
    ├── requirements.txt
    ├── config.env.example
    ├── Dockerfile
    ├── run_all.py
    ├── .dockerignore
    ├── seed/init_sessions.db  空初始化数据库（首次启动复制到 data/）
    ├── 启动.bat
    └── README.md

注意：本地包命名为 agent_builders，而不是 agents，避免遮蔽 pip 安装的 openai-agents 包（它的导入名也是 agents）。

## 五、快速开始

### 1. 安装依赖

    cd E:\Projects\AI\八斗学院\hub-YGkV\吕宗猛\week15\EmotionSupport-OpenAIAgents
    C:\SoftWare\miniconda3\envs\py312\python.exe -m pip install -r requirements.txt

### 2. 配置模型

首次打开 http://127.0.0.1:8613/ 时，页面会检查 SQLite 的 model_config 表。没有记录时会自动跳转到 /model-config 配置页；填写 Base URL、API Key、模型名称并保存后进入聊天。

config.env.example 中的模型字段只作为后端无页面调试时的兜底；实际模型配置以 SQLite 中的记录为准。Magpie 默认监听 127.0.0.1:3425，模型名必须是 workbuddy/deepseek-v4.1-flash；如果 Magpie 配置了鉴权，在页面里填入 API Key。

### 3. 启动两个进程

双击 启动.bat，或在两个终端分别执行：

    cd backend
    C:\SoftWare\miniconda3\envs\py312\python.exe main.py

    cd frontend
    C:\SoftWare\miniconda3\envs\py312\python.exe main.py

然后打开 http://127.0.0.1:8613/ 。

启动.bat 会打开两个命令行窗口：后端窗口显示 8623，前端窗口显示 8613。关闭对应窗口即可停止服务。

### 4. 只启动其中一个

- 只改 Agent 逻辑：重启后端窗口即可，前端页面不需要动。
- 只改页面样式：重启前端窗口即可，后端不受影响。

## 六、SQLite 会话与 5 轮上下文

- 后端启动时自动初始化 data/sessions.db，包含 sessions 与 messages 两张表。
- 每次新会话的第一条消息送入标题 Agent，用 LLM 生成一个中文短标题并写入 sessions.title。
- 每轮用户消息与助手回应都会写入 messages；助手消息的 meta_json 保存情感识别结果与回应 Agent。
- 聊天时后端从 SQLite 读取该会话最近 5 轮（最多 10 条消息）作为上下文，超过的部分不发送给模型。
- 点击历史会话时，页面先加载最近 5 条消息；点击“加载更早的 5 条”按 before_id 继续向前取 5 条，直到最早一条。

## 七、API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 查看框架、模型、Mock 状态、历史轮数、SQLite 路径、模型是否已配置 |
| GET | /api/model-config | 查询 SQLite 中的模型配置状态 |
| POST | /api/model-config | 保存 Base URL、API Key、模型名称到 SQLite |
| GET | /api/sessions | 历史会话列表（标题、更新时间、消息数） |
| GET | /api/sessions/{session_id}/messages?limit=5&before_id=... | 分页读取消息；before_id 用于继续加载更早的 5 条 |
| POST | /api/chat | 非流式，一次返回识别结果与回应 |
| POST | /api/chat/stream | SSE，实时推送 session / stage / emotion / reply / done 事件 |

POST 请求体：

    {
      "message": "最近压力好大，什么都做不好",
      "session_id": "已有会话的 id；新会话传 null"
    }

SSE 事件顺序：

    session -> stage(emotion) -> emotion -> stage(reply) -> reply -> done

## 八、离线演示

没有启动 Magpie 时，可以设置 MOCK_MODE=1，用本地情绪词典与模板跑通整条链路：

    set MOCK_MODE=1
    cd backend
    C:\SoftWare\miniconda3\envs\py312\python.exe smoke.py

离线模式只用于演示路由与页面，不代表真实模型效果。

## 九、自测

    cd backend
    C:\SoftWare\miniconda3\envs\py312\python.exe smoke.py

预期输出包含 3 个 PASS：正向、负面、中性。要测真实模型：

    set MOCK_MODE=0
    C:\SoftWare\miniconda3\envs\py312\python.exe smoke.py 1

最后参数 1 表示只跑第一个用例，避免一次调用过久。

## 十、Docker 构建（单镜像前后端）

Dockerfile 使用 python:3.12-slim-bookworm 作为基础镜像，采用多阶段构建，一个镜像同时包含后端与前端。

构建：

    cd E:\Projects\AI\八斗学院\hub-YGkV\吕宗猛\week15\EmotionSupport-OpenAIAgents
    docker build -t emotion-support-openai-agents .

运行（Windows Docker Desktop）：

    docker run --rm ^
      -p 8613:8613 -p 8623:8623 ^
      -v %cd%\data:/app/data ^
      emotion-support-openai-agents

说明：

- Dockerfile 不设置任何模型相关环境变量，模型配置全部由页面写入 SQLite。
- 容器启动时如果 /app/data/sessions.db 不存在，会自动从镜像内置的 /app/seed/init_sessions.db 复制一个空库。
- 首次打开页面会检查 SQLite 中的模型配置；如果不存在，会优先跳转到 /model-config 配置页。
- 在配置页填写 Base URL、API Key 与模型名称，保存后写入 SQLite，然后自动进入聊天。
- 如果 Magpie 跑在宿主机上，Base URL 填 http://host.docker.internal:3425/v1；Linux Docker 无法解析 host.docker.internal 时，启动容器加 --add-host=host.docker.internal:host-gateway。
- data 目录挂载到 /app/data，SQLite 会话库与模型配置都会保存在宿主机 data/sessions.db。

镜像体积控制：

- 多阶段构建，最终镜像不包含 pip 缓存和编译工具。
- 基础镜像选 slim，而不是完整 python:3.12。
- 如需进一步缩小，可将前端依赖拆成独立 requirements-frontend.txt，只安装 fastapi、uvicorn、httpx、python-dotenv。

## 十一、与 LangGraph 版的区别

| 对比项 | LangGraph 版 | OpenAI Agents 版 |
|---|---|---|
| 编排方式 | StateGraph 节点 + 条件边 | Python 顺序调用 Runner.run |
| Agent 表达 | 图节点函数 | Agent 对象 |
| 路由 | add_conditional_edges | 后端按 label 选择 Agent |
| 前端 | 相同 | 相同 |
| 模型 | Magpie 同一模型 | Magpie 同一模型 |

## 十二、已知限制

- 中性输入走规则兜底，不调用 LLM；这是为了保持 3 个 Agent 的边界清晰。
- 会话存储在本地 SQLite 文件，单机有效；没有用户账号与多端同步。
- 会话标题由 LLM 根据第一条消息生成，可能不够准确，可在后续版本增加手动改名。
- 情感识别是模型判断，存在误判；页面会同时展示置信度、强度与依据，便于人工复核。
- 当前只适配 Magpie 的 OpenAI 兼容接口；换其他网关时修改 .env 即可。
