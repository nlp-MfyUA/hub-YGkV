"""
作业二 · MCP Server

基于课堂代码 `2-fastmcp使用/2-兼容OpenAI-Agent/server.py`，
保留原有的 2 个工具（roll_dice / get_news），另外自己新增 3 个 MCP 工具：

    1. get_current_time  查询指定时区的当前时间        -> 返回 str
    2. calculate         安全地做四则运算（不用 eval）  -> 返回 dict
    3. get_weather       查询城市天气（mock 数据）      -> 返回 dict

启动：
    python server.py                 # SSE 传输，默认 0.0.0.0:8000
    python server.py --port 8001     # 换端口
"""
from __future__ import annotations

import argparse
import ast
import operator
import random
from datetime import datetime
from typing import Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp import FastMCP

# 工具名字、传入参数类型、返回值类型、函数的注释（工具说明）
# —— 这四样东西会通过 MCP 协议传给大模型，模型据此选择工具并生成参数
mcp = FastMCP(name="Dice Roller")


# --------------------------------------------------------------------------- #
# 原有工具（与课堂代码保持一致）
# --------------------------------------------------------------------------- #
@mcp.tool
def roll_dice(n_dice: int) -> list[int]:
    """Roll `n_dice` 6-sided dice and return the results."""
    # 与课堂原始代码保持一致：说明写的是 6 面骰子，实际返回 10~60（原代码如此，这里没有改动）
    return [random.randint(10, 60) for _ in range(n_dice)]


@mcp.tool
def get_news() -> Union[int, str]:
    """Get latest news."""
    return "最新消息 Qwen4 is coming!"


# --------------------------------------------------------------------------- #
# 新增工具 1：时间查询
# --------------------------------------------------------------------------- #
@mcp.tool
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """Get the current date and time in the given timezone.

    Args:
        timezone: IANA timezone name, e.g. "Asia/Shanghai", "UTC", "America/New_York".
    """
    try:
        now = datetime.now(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        return f"Unknown timezone: {timezone}. Please use an IANA name like 'Asia/Shanghai'."

    weekday = "一二三四五六日"[now.weekday()]
    return f"{now.strftime('%Y-%m-%d %H:%M:%S')} (星期{weekday}, {timezone})"


# --------------------------------------------------------------------------- #
# 新增工具 2：四则运算（AST 白名单解析，不用 eval，避免执行任意代码）
# --------------------------------------------------------------------------- #
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_POW_EXPONENT = 100  # 防止 9**9**9 这类把进程算挂的表达式


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric constants are supported")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW_EXPONENT:
            raise ValueError(f"exponent too large (max {_MAX_POW_EXPONENT})")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")


@mcp.tool
def calculate(expression: str) -> dict:
    """Evaluate a pure arithmetic expression (+ - * / // % ** and parentheses).

    Args:
        expression: e.g. "(123 + 456) * 2 / 3".
    """
    try:
        value = _eval_node(ast.parse(expression, mode="eval"))
    except ZeroDivisionError:
        return {"expression": expression, "error": "division by zero"}
    except (SyntaxError, ValueError, TypeError) as exc:
        return {"expression": expression, "error": f"invalid expression: {exc}"}

    result = int(value) if isinstance(value, float) and value.is_integer() else value
    return {"expression": expression, "result": result}


# --------------------------------------------------------------------------- #
# 新增工具 3：天气查询（教学演示用的 mock 数据，不是真实气象数据）
# --------------------------------------------------------------------------- #
_CONDITIONS = ["晴", "多云", "阴", "小雨", "雷阵雨", "雾"]


@mcp.tool
def get_weather(city: str) -> dict:
    """Get the current weather of a city (demo data, not a real weather service).

    Args:
        city: city name in Chinese or English, e.g. "深圳" or "shenzhen".
    """
    # 用城市名做随机种子，保证同一个城市反复查询结果稳定，方便演示
    rng = random.Random(city.strip().lower())
    return {
        "city": city,
        "condition": rng.choice(_CONDITIONS),
        "temperature_c": rng.randint(15, 33),
        "humidity_percent": rng.randint(35, 90),
        "wind": f"{rng.choice(['东', '南', '西', '北'])}风 {rng.randint(1, 5)} 级",
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "mock data（教学演示，非真实气象数据）",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FastMCP server (SSE)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # SSE 传输：client 通过 http://<host>:<port>/sse 连接
    mcp.run(transport="sse", host=args.host, port=args.port)
