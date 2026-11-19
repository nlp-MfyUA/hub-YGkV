# 心屿 · 情感陪伴（LangGraph 版）

基于 LangGraph StateGraph 的多 Agent 情绪支持演示。用户在前端输入一句话，后端先识别情绪，再按情绪结果路由到对应的回应 Agent。

## 一、项目定位

- 前端进程：只负责页面与用户输入，默认端口 8612。
- 页面特性：新消息与流式文字自动滚动到最底部；每轮回应结束显示绿色「回应完成」标识。
- 后端进程：接收前端请求，串联情感识别与回应 Agent，默认端口 8622。
- 多 Agent：3 个 Agent，加上中性规则兜底。
- 对话上下文：后端从 SQLite 读取最近 5 轮，超过 5 轮自动截断。
- 会话记录：本地 SQLite 持久化；每次聊天开始时由 LLM 生成会话标题。
- 模型：本地 Magpie 网关的 workbuddy/deepseek-v4.1-flash。

## 二、架构

    浏览器
      │  http://127.0.0.1:8612
      ▼
    前端进程（FastAPI + 原生 HTML/CSS/JS）
      │  /api/* 反向代理
      ▼
    后端进程（FastAPI）
      │  SQLite（data/sessions.db）
      ▼
    LangGraph StateGraph
      ├─ 情感识别 Agent
      ├─ 条件边：positive / negative / neutral
      ├─ 正向鼓励 Agent
      ├─ 负面排解 Agent
      └─ 中性规则兜底（不调用第 4 个 Agent）

前端与后端是两个独立的 Python 进程，可以分别启动、分别重启。前端通过 httpx 把 /api 请求代理到后端，浏览器只需要访问 8612。

## 三、多 Agent 设计

| 序号 | Agent / 节点 | 职责 | 触发条件 |
|---|---|---|---|
| 1 | 情感识别 Agent | 输出 label、confidence、intensity、reason、keywords | 每次请求 |
| 2 | 正向鼓励 Agent | 具体肯定用户的努力与感受，给出温和延伸建议 | label = positive |
| 3 | 负面排解 Agent | 先共情命名情绪，再给最小可控动作或调节练习 | label = negative |
| - | 中性规则兜底 | 用稳定模板陪用户把话说完，不额外调用模型 | label = neutral |

说明：题目要求“正向则鼓励，负面则排解”，中性输入没有明确归属，因此用规则兜底，避免为了凑分支再加一个不必要的 Agent。这样仍然是 3 个 Agent。

## 四、目录结构

    EmotionSupport-LangGraph/
    ├── backend/
    │   ├── main.py              后端进程入口（FastAPI，8622）
    │   ├── config.py            Magpie、端口、历史轮数配置
    │   ├── schemas.py           ChatTurn / EmotionResult
    │   ├── graph.py             LangGraph StateGraph 与 3 个 Agent 节点
    │   ├── pipeline.py          历史截断、事件流编排
    │   ├── storage.py           SQLite 会话存储（sessions / messages）
    │   ├── agents/
    │   │   ├── emotion_agent.py     情感识别 Agent
    │   │   ├── support_agents.py    正向鼓励 / 负面排解 Agent
    │   │   ├── title_agent.py       会话标题生成 Agent
    │   │   └── base.py              JSON 解析、模型客户端、离线模拟
    │   └── smoke.py             命令行冒烟测试
    ├── data/sessions.db          运行后自动生成的本地会话库
    ├── frontend/
    │   ├── main.py              前端进程入口（FastAPI + 静态资源 + /api 代理，8612）
    │   └── web/
    │       ├── index.html
    │       ├── style.css
    │       └── app.js
    ├── requirements.txt
    ├── config.env.example
    ├── 启动.bat
    └── README.md

## 五、快速开始

### 1. 安装依赖

    cd E:\Projects\AI\八斗学院\hub-YGkV\吕宗猛\week15\EmotionSupport-LangGraph
    C:\SoftWare\miniconda3\envs\py312\python.exe -m pip install -r requirements.txt

### 2. 配置模型

复制 config.env.example 为 .env，确认：

    BASE_URL=http://127.0.0.1:3425/v1
    API_KEY=
    MODEL_NAME=workbuddy/deepseek-v4.1-flash
    TITLE_MODEL=workbuddy/deepseek-v4.1-flash
    SESSION_DB_PATH=./data/sessions.db
    MOCK_MODE=0

Magpie 默认监听 127.0.0.1:3425，模型名必须是 workbuddy/deepseek-v4.1-flash。当前网关本地无需 API Key；如果主人给 Magpie 配了鉴权，把 API_KEY 填上即可。

### 3. 启动两个进程

双击 启动.bat，或在两个终端分别执行：

    cd backend
    C:\SoftWare\miniconda3\envs\py312\python.exe main.py

    cd frontend
    C:\SoftWare\miniconda3\envs\py312\python.exe main.py

然后打开 http://127.0.0.1:8612/ 。

启动.bat 会打开两个命令行窗口：后端窗口显示 8622，前端窗口显示 8612。关闭对应窗口即可停止服务。

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
| GET | /api/health | 查看框架、模型、Mock 状态、历史轮数、SQLite 路径 |
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

## 十、与 OpenAI Agents 版的区别

| 对比项 | LangGraph 版 | OpenAI Agents 版 |
|---|---|---|
| 编排方式 | StateGraph 节点 + 条件边 | Python 顺序调用 Runner.run |
| Agent 表达 | 图节点函数 | Agent 对象 |
| 路由 | add_conditional_edges | 后端按 label 选择 Agent |
| 前端 | 相同 | 相同 |
| 模型 | Magpie 同一模型 | Magpie 同一模型 |

## 十一、已知限制

- 中性输入走规则兜底，不调用 LLM；这是为了保持 3 个 Agent 的边界清晰。
- 会话存储在本地 SQLite 文件，单机有效；没有用户账号与多端同步。
- 会话标题由 LLM 根据第一条消息生成，可能不够准确，可在后续版本增加手动改名。
- 情感识别是模型判断，存在误判；页面会同时展示置信度、强度与依据，便于人工复核。
- 当前只适配 Magpie 的 OpenAI 兼容接口；换其他网关时修改 .env 即可。
