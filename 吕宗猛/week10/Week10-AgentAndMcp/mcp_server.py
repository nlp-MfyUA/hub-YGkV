import time

from fastmcp import FastMCP

mcp = FastMCP("My MCP Server")


@mcp.tool
def get_weather(city: str):
    """根据城市查询天气"""
    print(f"时间:{time.strftime('%Y-%m-%d %H:%M:%S')},城市:{city},天气:晴朗")
    return f"时间:{time.strftime('%Y-%m-%d %H:%M:%S')},城市:{city},天气:晴朗"

@mcp.tool
def calc(num_a: int, num_b: int):
    """计算两个数的乘积"""
    print(f'{num_a} * {num_b} = {num_a * num_b}')
    return num_a * num_b

@mcp.tool
def get_time():
    """得到当前时间，并格式化输出"""
    print(f"时间:{time.strftime('%Y-%m-%d %H:%M:%S')}")
    return f"时间:{time.strftime('%Y-%m-%d %H:%M:%S')}"

if __name__ == "__main__":
    mcp.run(transport="http", port=8000)