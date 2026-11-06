import random
from fastmcp import FastMCP
from typing import Union
from typing import Annotated, Literal
from pydantic import Field
from datetime import datetime
from zoneinfo import ZoneInfo

mcp = FastMCP(name="Dice Roller")

# 工具名字、传入参数类型、返回值类型、函数的注释（工具说明）


@mcp.tool
def roll_dice(n_dice: int) -> list[int]:
    """Roll `n_dice` 6-sided dice and return the results."""
    return [random.randint(10, 60) for _ in range(n_dice)]


@mcp.tool
def get_news() -> Union[int, str]:
    """Get latest news."""
    return "最新消息 Qwen4 is coming!"


@mcp.tool
def get_current_time(
    timezone: Annotated[
        str, Field(description="IANA 时区名，例如 Asia/Shanghai")
    ] = "Asia/Shanghai",
) -> str:
    """查询指定时区的当前日期和时间。用户问“现在几点”“今天几号”时使用。"""
    return datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S %Z")


@mcp.tool
def calculate(
    a: float,
    b: float,
    op: Annotated[
        Literal["add", "sub", "mul", "div"], Field(description="运算类型：加/减/乘/除")
    ],
) -> float:
    """对两个数字做四则运算。用户要求算数时使用。"""
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "mul":
        return a * b
    if b == 0:
        raise ValueError("除数不能为 0")
    return a / b


@mcp.tool
def get_weather(
    city: Annotated[str, Field(description="城市名，例如 北京")],
) -> dict:
    """查询指定城市的当前天气。用户问天气时使用。"""
    fake = {
        "北京": {"temp": 22, "condition": "晴"},
        "上海": {"temp": 26, "condition": "多云"},
    }
    return fake.get(city, {"temp": 20, "condition": "未知"})


if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)
