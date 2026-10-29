# -*- coding: utf-8 -*-
"""
智能语种检测与翻译助手(OpenAI Agents + MCP)

需求一: 用户输入文本 -> LanguageDetector 判断语种 -> Translator 翻译
        (规则: 中文→英文, 其他语言→中文) -> 输出 JSON:
        {"query_input": "", "language": "", "result": ""}

需求二: 翻译能力由 MCP 工具提供 —— mcp/translation_server.py(基于课程基线
        mcp_server_demo 扩展)暴露 3 个翻译类工具: detect_language /
        translate_text / get_language_info; 两个 Agent 通过 MCP 协议调用它们。

运行(本地 conda py312 环境):
    conda activate py312
    cp .env.example .env      # 然后编辑 .env 填入 OPENAI_API_KEY
    python main.py "你好，世界"
    python main.py            # 不带参数则进入交互式输入
"""
import asyncio
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from agents import Runner, set_tracing_disabled
from agents.mcp import MCPServerStdio

from config import settings
from translate_agents import create_language_agent, create_translation_agent

# 本地运行无需上报 OpenAI  Tracing, 关闭以避免无谓请求
set_tracing_disabled(True)

PROJECT_ROOT = Path(__file__).resolve().parent
SERVER_SCRIPT = PROJECT_ROOT / "mcp" / "translation_server.py"


def _extract_json(text: str) -> dict:
    """从 Agent 输出中提取 JSON 对象(容忍 ```json 代码块和前后缀文字)。"""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


async def run_pipeline(query: str) -> dict:
    """完整流水线: 语种检测 -> 翻译路由 -> 组装输出 JSON。"""
    # 以子进程方式拉起 MCP Server(stdio 通信), 与课程基线代码接入方式一致
    mcp_server = MCPServerStdio(
        name="translation-mcp-server",
        params={"command": sys.executable, "args": [str(SERVER_SCRIPT)]},
    )
    async with mcp_server:
        # 两个 Agent 共享同一个 MCP Server 连接
        language_agent = create_language_agent(mcp_server, model=settings.agent_model)
        translation_agent = create_translation_agent(mcp_server, model=settings.agent_model)

        # 第一步: 语种检测 Agent(调用 MCP 工具 detect_language)
        r1 = await Runner.run(language_agent, f"请检测以下文本的语种: {query}")
        info = _extract_json(r1.final_output)
        src_code = info.get("language", "unknown")
        src_name = info.get("language_name", "未知")

        # 第二步: 翻译路由 —— 中文→英文, 其他语言→中文
        tgt_code = "en" if src_code == "zh" else "zh"
        tgt_name = "英文" if tgt_code == "en" else "中文"
        r2 = await Runner.run(
            translation_agent,
            f"待翻译文本: {query}\n"
            f"源语言: {src_name}({src_code})\n"
            f"目标语言: {tgt_name}({tgt_code})\n"
            f"请调用 translate_text 工具完成翻译。",
        )
        result = (r2.final_output or "").strip().strip('"').strip("'").strip()

        # 第三步: 按需求规定的 JSON 格式输出
        return {"query_input": query, "language": src_name, "result": result}


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    if not settings.llm_ready:
        print("⚠️ 未检测到 OPENAI_API_KEY, 请先按 .env.example 配置 .env", file=sys.stderr)
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:]).strip()
    else:
        query = input("请输入要检测并翻译的文本: ").strip()
    if not query:
        print("输入为空, 退出。", file=sys.stderr)
        sys.exit(1)
    output = asyncio.run(run_pipeline(query))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
