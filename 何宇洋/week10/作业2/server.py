import random
import re

from fastmcp import FastMCP
from typing import Literal

mcp = FastMCP(name="Homework MCP Server")


# ========== 原有工具 ==========

@mcp.tool
def roll_dice(n_dice: int) -> list[int]:
    """投掷 n_dice 个六面骰子，返回每次投掷结果。"""
    if not 1 <= n_dice <= 100:
        raise ValueError("骰子数量必须在 1 到 100 之间")

    return [random.randint(1, 6) for _ in range(n_dice)]


@mcp.tool
def get_news() -> str:
    """获取示例新闻。注意：这是模拟新闻，并非实时数据。"""
    return "最新消息：Qwen 发布了新的模型！"


# ========== 新增工具 1：计算器 ==========

@mcp.tool
def calculate(
    a: float,
    b: float,
    operation: Literal["add", "subtract", "multiply", "divide"]
) -> float:
    """
    对两个数字进行四则运算。

    operation:
    add: 加法
    subtract: 减法
    multiply: 乘法
    divide: 除法
    """
    if operation == "add":
        return a + b

    elif operation == "subtract":
        return a - b

    elif operation == "multiply":
        return a * b

    elif operation == "divide":
        if b == 0:
            raise ValueError("除数不能为 0")
        return a / b

    raise ValueError("不支持的运算类型")


# ========== 新增工具 2：文本统计 ==========

@mcp.tool
def text_statistics(text: str) -> dict:
    """
    统计文本的字符总数、汉字数量、
    英文单词数量和数字字符数量。
    """

    chinese_count = len(
        re.findall(r"[\u4e00-\u9fff]", text)
    )

    english_words = len(
        re.findall(r"[a-zA-Z]+", text)
    )

    digit_count = sum(
        char.isdigit() for char in text
    )

    return {
        "total_characters": len(text),
        "chinese_characters": chinese_count,
        "english_words": english_words,
        "digit_characters": digit_count
    }


# ========== 新增工具 3：温度转换 ==========

@mcp.tool
def convert_temperature(
    value: float,
    from_unit: Literal["C", "F"],
    to_unit: Literal["C", "F"]
) -> float:
    """
    摄氏度与华氏度转换。

    C: 摄氏度
    F: 华氏度
    """

    if from_unit == to_unit:
        return value

    if from_unit == "C" and to_unit == "F":
        return round(value * 9 / 5 + 32, 2)

    if from_unit == "F" and to_unit == "C":
        return round((value - 32) * 5 / 9, 2)

    raise ValueError("不支持的温度单位")


if __name__ == "__main__":
    mcp.run(
        transport="sse",
        host="127.0.0.1",
        port=8000
    )