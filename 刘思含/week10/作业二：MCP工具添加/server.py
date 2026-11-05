import random
from datetime import datetime
from fastmcp import FastMCP
from typing import Union
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
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


@mcp.tool
def get_current_time() -> str:
    """Return the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@mcp.tool
def reverse_text(text: str) -> str:
    """Reverse the given text."""
    return text[::-1]


if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)