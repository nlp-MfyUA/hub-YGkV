import random
from fastmcp import FastMCP

mcp = FastMCP(name="Dice Roller")

@mcp.tool
def roll_dice(n_dice: int) -> list[int]:
    """Roll `n_dice` 6-sided dice and return the results."""
    return [random.randint(10, 60) for _ in range(n_dice)]

@mcp.tool
def get_news() -> str:
    """Get latest news."""
    return "最新消息 Qwen4 is coming!"


if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)