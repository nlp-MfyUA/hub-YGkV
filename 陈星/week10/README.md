# 陈星 week10 作业

作业一：多 Agent 语种识别与互译（`task1.py`），输出固定 JSON：`query_input` / `language` / `result`。
作业二：FastMCP 三个工具 + Agent 调用（`task2.py` 单文件；`--server` 只启服务端，默认模式启服务端再让 Agent 提问）。

## 环境

```bash
pip install openai-agents fastmcp pydantic
export OPENAI_API_KEY=你的密钥
# 作业二默认走 DashScope 兼容接口，可按需覆盖：
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL=qwen-max
# 作业一也可改用 WorkBuddy：设置 WB_PUBLISHABLE_KEY（或本地 README 中的密钥）
```

## 运行

```bash
# 作业一
python task1.py "今天天气不错"
python task1.py "Hello, nice to meet you"

# 作业二（单文件）
python task2.py              # 启动服务器 + Agent 提问
python task2.py --server     # 仅启动 MCP 服务器
```
