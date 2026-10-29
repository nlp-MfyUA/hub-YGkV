# lang_translate_agent — 智能语种检测与翻译助手

基于 **OpenAI Agents SDK + MCP** 的多语言处理应用：用户输入一段文本，先由「语种检测 Agent」判断语种，再由「翻译 Agent」按规则翻译（**中文 → 英文，其他语言 → 中文**），最终输出规定格式的 JSON。

## 功能一览

| 需求 | 内容 |
| --- | --- |
| 需求一 | 双 Agent 应用：`LanguageDetector`（语种判断）+ `Translator`（按语言路由翻译），输出 `{"query_input", "language", "result"}` |
| 需求二 | 基于课程基线代码（`mcp_server_demo`，2-兼容OpenAI-Agent）扩展 MCP Server，新增 **3 个翻译类工具**：`detect_language` / `translate_text` / `get_language_info`，并由 Agent 通过 MCP 协议调用 |

## 架构

```
用户输入文本
     │
     ▼
┌─────────────────────────── main.py (OpenAI Agents SDK) ───────────────────────────┐
│                                                                                  │
│   Runner.run(LanguageDetector) ──MCP(stdio)──▶ detect_language(text)              │
│        │ 得到 {"language":"ja","language_name":"日语"}                             │
│        ▼                                                                         │
│   路由规则: 中文→英文 / 其他→中文                                                    │
│        ▼                                                                         │
│   Runner.run(Translator) ──────MCP(stdio)──▶ translate_text(text, src, tgt)        │
│        │                                          （内部调用 OpenAI 兼容大模型）     │
│        ▼                                                                         │
│   输出 {"query_input": ..., "language": ..., "result": ...}                       │
└──────────────────────────────────────────────────────────────────────────────────┘
                                     ▲
                    mcp/translation_server.py (基线 + 3 个翻译类工具)
```

## 环境要求（本地 conda py312）

- Python 3.12（conda 环境 `py312`，已验证 3.12.13）
- 依赖：`openai-agents>=0.20.0`、`mcp>=2.1.1`、`openai>=2.54.0`、`python-dotenv>=1.2.2`（py312 环境已全部预装）
- 一个 OpenAI 兼容接口的 API Key（OpenAI 官方或 OneAPI 等网关均可）

## 快速开始

```bash
# 1. 激活环境
conda activate py312

# 2. 配置密钥
cd week10/lang_translate_agent
cp .env.example .env      # 编辑 .env 填入 OPENAI_API_KEY（必要时改 OPENAI_BASE_URL）

# 3. 运行
python main.py "你好，世界"     # 中文 → 英文
python main.py "Hello, world"  # 英文 → 中文
python main.py "こんにちは"     # 日语 → 中文
python main.py                 # 交互式输入
```

输出示例：

```json
{
  "query_input": "你好，世界",
  "language": "中文",
  "result": "Hello, world"
}
```

## 测试

```bash
python tests/test_mcp_tools.py   # 离线测试: 直接调用 handler 验证 5 个工具 + Resources/Prompts
python tests/test_stdio.py       # 真实 stdio JSON-RPC 握手测试(模拟客户端拉起 Server)
python tests/test_pipeline.py    # 主流程编排测试(mock Runner, 验证路由规则与输出 JSON 格式)
```

## 目录结构

```
lang_translate_agent/
├── main.py                        # 入口: 串起两个 Agent, 输出规定 JSON
├── config.py                      # 配置加载(.env / 环境变量)
├── requirements.txt               # 依赖清单
├── .env.example                   # 配置模板
├── mcp/
│   └── translation_server.py      # MCP Server: 基线能力 + 3 个翻译类工具
├── translate_agents/
│   ├── language_agent.py          # Agent 1: 语种检测专家
│   └── translation_agent.py       # Agent 2: 翻译专家
└── tests/
    ├── test_mcp_tools.py          # 离线 handler 测试
    ├── test_stdio.py              # 真实 stdio 握手测试
    └── test_pipeline.py           # 主流程编排测试(mock Runner)
```

## 说明

- `mcp/translation_server.py` 沿用课程基线代码的 `Server(..., on_list_tools=..., on_call_tool=...)` 构造函数回调注册风格（适配 mcp 2.x，装饰器风格已在 2.x 移除），并完整保留基线工具与 Resources/Prompts。
- `detect_language` 为纯本地规则实现（Unicode 区段 + 拉丁语言停用词投票），不消耗 Token；`translate_text` 内部调用 OpenAI 兼容大模型完成翻译；`get_language_info` 基于内置语言元数据表。
- 需求文档见 `../需求文档.md`。
