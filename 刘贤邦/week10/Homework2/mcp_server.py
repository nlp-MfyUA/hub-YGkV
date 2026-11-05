import fastmcp
import datetime

mcp = fastmcp.FastMCP("my_mcp")

@mcp.tool
def hello(name: str) -> str:
    """say hello"""
    return f"Hello {name}"

@mcp.tool
def get_weather(city: str) -> str:
    """get city weather"""
    return f"{city}: 晴天，50°"

@mcp.tool
def get_date() -> str:
    """get date"""
    today = datetime.date.today()
    return f"{today.year}-{today.month}-{today.day}"


if __name__ == "__main__":
    mcp.run("http", port=8000)
