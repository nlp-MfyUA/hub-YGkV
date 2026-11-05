# 作业二：出境旅行助手 —— OpenAI Agents 框架调用 FastMCP 工具 + 格式化 JSON 输出
#
# 应用场景：用户计划出境旅行，向助手提问，助手自动选择并调用 3 个 MCP 工具后作答：
#   1. get_weather(city)                        查询城市天气
#   2. get_exchange_rate(amount, from, to)      货币汇率换算
#   3. get_attractions(city)                    城市景点推荐
#
# 使用方式（单文件即可运行，客户端会自动以子进程方式拉起 MCP Server）：
#   python 作业二.py           # 默认客户端模式：自动启动 MCP Server 子进程 + Agent 对话循环
#   python 作业二.py server    # 手动以 MCP Server 模式运行（调试用，SSE 端口 8801）
#
# 代码组织（参考 2-fastmcp使用/2-兼容OpenAI-Agent 的 server.py / client.py / fastapi_demo.py）：
#   - 配置读取：同 作业一.py（.env + load_dotenv）
#   - MCP Server 部分：同 server.py（FastMCP + @mcp.tool + SSE 传输）
#   - Agent 客户端部分：同 client.py（MCPServerSse + Agent(mcp_servers=...)）
#   - 结构化输出：同 作业一.py（宽松模式 + 自定义容错解析 Schema）

from pathlib import Path

from dotenv import load_dotenv

# .env 位于项目根目录（本文件的上一级目录），用 __file__ 定位，保证从任意工作目录运行都能找到
# override=True：强制用 .env 的值覆盖已存在的同名环境变量
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time

import msvcrt  # Windows 标准库：用于逐字符读取键盘输入、捕捉 ESC 键

from pydantic import BaseModel, ValidationError

# load_dotenv 会把 .env 中的键值对写入环境变量 os.environ，这里读取出来
BASE_URL = os.getenv("OPENAI_BASE_URL")
API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL")

# 简单校验：确认配置读取成功（key 只显示前8位，避免泄露）
assert BASE_URL and API_KEY, ".env 读取失败，请检查文件路径和内容"
print(f"已加载配置: BASE_URL={BASE_URL}, API_KEY={API_KEY[:8]}****")

from fastmcp import FastMCP
from openai import AsyncOpenAI
from agents import Agent, OpenAIChatCompletionsModel, Runner
from agents.mcp.server import MCPServerSse
from agents import set_default_openai_api, set_tracing_disabled

set_default_openai_api("chat_completions")  # 国内模型兼容接口使用 chat completions
set_tracing_disabled(True)  # 关闭 OpenAI 云端链路追踪（国内接口不支持）

# ============================================================
# 第一部分：MCP Server（参考 server.py）
# ============================================================

mcp = FastMCP(name="Travel Assistant")

# 模拟数据源（真实项目中这里会调用天气 API / 汇率 API / 数据库）
WEATHER_DB = {
    "北京": "晴，气温 12°C，空气质量优",
    "上海": "多云，气温 18°C，空气质量良",
    "东京": "小雨，气温 15°C，建议带伞",
    "巴黎": "阴，气温 11°C",
    "纽约": "晴，气温 9°C",
    "伦敦": "中雨，气温 8°C，建议带伞",
}

# 以 CNY 为基准的模拟汇率表
RATES_TO_CNY = {"CNY": 1.0, "USD": 7.2, "EUR": 7.8, "JPY": 0.048, "GBP": 9.1}

ATTRACTIONS_DB = {
    "北京": ["故宫", "长城", "颐和园", "南锣鼓巷"],
    "上海": ["外滩", "豫园", "上海迪士尼", "武康路"],
    "东京": ["浅草寺", "涩谷十字路口", "东京塔", "秋叶原", "明治神宫"],
    "巴黎": ["埃菲尔铁塔", "卢浮宫", "凯旋门", "塞纳河游船"],
    "纽约": ["自由女神像", "中央公园", "大都会博物馆", "时代广场"],
    "伦敦": ["大本钟", "大英博物馆", "伦敦眼", "塔桥"],
}


@mcp.tool
def get_weather(city: str) -> str:
    """Get the weather of a city. Supported cities: 北京, 上海, 东京, 巴黎, 纽约, 伦敦."""
    weather = WEATHER_DB.get(city)
    return f"{city}的天气：{weather}" if weather else f"暂无 {city} 的天气数据，支持的城市：{'、'.join(WEATHER_DB)}"


@mcp.tool
def get_exchange_rate(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert money between currencies. Supported currencies: CNY, USD, EUR, JPY, GBP."""
    f, t = from_currency.upper(), to_currency.upper()
    if f not in RATES_TO_CNY or t not in RATES_TO_CNY:
        return f"暂不支持的币种（支持：{'、'.join(RATES_TO_CNY)}）"
    rate = RATES_TO_CNY[f] / RATES_TO_CNY[t]  # 经 CNY 桥接换算
    converted = amount * rate
    return f"{amount} {f} ≈ {converted:.2f} {t}（汇率 {rate:.4f}，模拟数据）"


@mcp.tool
def get_attractions(city: str) -> str:
    """Get recommended attractions of a city. Supported cities: 北京, 上海, 东京, 巴黎, 纽约, 伦敦."""
    spots = ATTRACTIONS_DB.get(city)
    return f"{city}推荐景点：{'、'.join(spots)}" if spots else f"暂无 {city} 的景点数据，支持的城市：{'、'.join(ATTRACTIONS_DB)}"


def run_server_mode():
    """以 MCP Server 模式运行（SSE 传输，端口 8801），日志写入 mcp_server.log"""
    log_path = Path(__file__).parent / "mcp_server.log"
    with open(log_path, "w", encoding="utf-8") as log_file:
        # uvicorn 的启动日志输出到文件，避免和客户端交互混在一起
        sys.stdout = log_file
        sys.stderr = log_file
        print(f"[{time.strftime('%H:%M:%S')}] MCP Server 启动中... SSE: http://127.0.0.1:8801/sse")
        mcp.run(transport="sse", host="127.0.0.1", port=8801)


# ============================================================
# 第二部分：格式化输出定义（同 作业一.py 的宽松模式方案）
# ============================================================

# 最终输出的 JSON 结构定义（Pydantic 模型 -> JSON Schema 约束大模型输出）
class AssistantOutput(BaseModel):
    query_input: str       # 用户输入的问题（原样返回）
    tools_used: list[str]  # 本次回答实际调用的 MCP 工具名列表
    answer: str            # 基于工具调用结果的最终回答


def clean_model_output(text: str) -> str:
    """清理大模型输出中的杂质：markdown 代码块围栏、围栏外的多余文字。
    国内模型经常返回 ```json {...} ``` 格式，导致 JSON 解析失败。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    # 兜底：截取第一个 { 到最后一个 } 之间的内容（应对 JSON 前后带解释文字的情况）
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text.strip()


# ============================================================
# 第三部分：Agent 客户端（参考 client.py）
# ============================================================

SSE_URL = "http://127.0.0.1:8801/sse"


def start_mcp_server_subprocess() -> subprocess.Popen:
    """以子进程方式启动本文件的 MCP Server 模式，返回进程句柄用于退出时清理"""
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "server"],
        cwd=str(Path(__file__).parent),
    )
    return proc


def wait_for_port(port: int, timeout: float = 15.0) -> bool:
    """等待端口就绪（MCP Server 启动需要 1~2 秒），避免客户端连接过早失败"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def input_with_esc(prompt: str) -> str | None:
    """逐字符读取一行输入（Windows）：
    - 按 Enter 返回已输入的内容
    - 按 ESC 立即返回 None（用于退出循环）
    - 支持退格键删除；忽略方向键等特殊按键
    """
    print(prompt, end="", flush=True)
    chars: list[str] = []
    while True:
        ch = msvcrt.getwch()
        if ch == "\x1b":  # ESC 键
            print()
            return None
        elif ch in ("\r", "\n"):  # Enter 键，输入结束
            print()
            return "".join(chars)
        elif ch in ("\x00", "\xe0"):  # 特殊按键（方向键等）发送两字节，读掉第二个
            msvcrt.getwch()
        elif ch == "\x08":  # 退格键
            if chars:
                chars.pop()
                print("\b \b", end="", flush=True)
        elif ch == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        else:
            chars.append(ch)
            print(ch, end="", flush=True)


async def run_chat(server) -> None:
    """Agent 对话主循环：用户提问 -> Agent 选择工具 -> MCP 调用 -> 格式化输出"""
    # 和 client.py 一样：显式构建模型客户端（使用 .env 中的国内兼容接口）
    external_client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    # step1: list tool —— 打印 MCP Server 提供的工具清单
    tools = await server.list_tools()
    print("当前 MCP Server 可用工具：")
    for t in tools:
        print(f"  - {t.name}: {t.description}")

    agent = Agent(
        name="TravelAssistant",
        model=OpenAIChatCompletionsModel(model=MODEL, openai_client=external_client),
        instructions=(
            "你是一个出境旅行助手，可以调用以下 MCP 工具回答用户问题：\n"
            "- get_weather(city)：查询城市天气\n"
            "- get_exchange_rate(amount, from_currency, to_currency)：货币汇率换算\n"
            "- get_attractions(city)：查询城市景点推荐\n"
            "规则：\n"
            "1. 根据问题自主选择工具，一次可以组合调用多个工具；与旅行无关的问题直接用知识回答并如实说明未调用工具；\n"
            "2. answer 必须基于工具返回的真实结果回答，禁止编造数据；\n"
            "3. tools_used 填写本次实际调用的工具英文名列表（未调用则为空列表）；\n"
            "4. query_input 原样保留用户输入；\n"
            "5. 直接输出 JSON 本体，禁止使用 markdown 代码块（```）包裹，禁止输出任何解释文字。"
        ),
        mcp_servers=[server],  # 挂载 MCP 工具：list tool -> select tool -> execute tool -> 总结
        # 注意：这里故意不设置 output_type！
        # 实测国内兼容接口（智谱）上 response_format(json_schema) 与 function call(tools)
        # 同时设置时工具调用会被忽略，模型会凭空编造答案。
        # 改为：让模型自由调用工具后按 instructions 约定输出 JSON 文本，本地再解析校验。
    )

    # while 循环：持续接收用户输入，按 ESC 键退出
    while True:
        text = input_with_esc("\n请输入你的旅行问题（按 ESC 退出）: ")

        if text is None:  # ESC 被按下
            print("已按 ESC，退出程序。")
            break
        if not text.strip():  # 空输入跳过
            continue

        # step2~4: 大模型选择工具(function call) -> mcp client 执行工具 -> 结果汇总回答
        result = await Runner.run(agent, text)

        # 附：从运行记录中提取实际发生的工具调用（比模型自述的 tools_used 更可靠）
        real_calls = [
            getattr(getattr(item, "raw_item", None), "name", "")
            for item in result.new_items
            if type(item).__name__ == "ToolCallItem"
        ]
        if real_calls:
            print(f"[实际调用的工具] {real_calls}")

        # 本地解析格式化输出（宽松模式的等价实现）：
        # 清理 markdown 围栏等杂质 -> pydantic 校验为 AssistantOutput 对象 -> 序列化 JSON
        try:
            output = AssistantOutput.model_validate_json(clean_model_output(result.final_output))
        except ValidationError as e:
            print(f"JSON 解析失败: {e}\n模型原始输出: {result.final_output}")
            continue
        print(json.dumps(output.model_dump(), ensure_ascii=False, indent=2))


async def main():
    # 自动拉起 MCP Server 子进程，退出时自动清理
    print("正在启动 MCP Server 子进程（SSE :8801）...")
    proc = start_mcp_server_subprocess()
    try:
        if not wait_for_port(8801):
            proc.kill()
            raise RuntimeError("MCP Server 启动超时，请查看 mcp_server.log")
        print("MCP Server 已就绪")

        async with MCPServerSse(
            name="Travel Assistant Server",
            params={"url": SSE_URL},  # mcp client 通过 http sse 方式与 server 沟通
        ) as server:
            await run_chat(server)
    finally:
        proc.terminate()  # 无论正常/异常退出，都回收子进程
        print("MCP Server 子进程已停止")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        run_server_mode()  # 服务模式
    else:
        asyncio.run(main())  # 客户端模式
