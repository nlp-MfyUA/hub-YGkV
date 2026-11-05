import os
os.environ.setdefault("FASTMCP_PORT", "8000")

import random
from mcp.server.fastmcp import FastMCP
from typing import Union
mcp = FastMCP(name="Dice Roller")

# 工具名字、传入参数类型、返回值类型、函数的注释（工具说明）

@mcp.tool()
def roll_dice(n_dice: int) -> list[int]:
    """Roll `n_dice` 6-sided dice and return the results."""
    return [random.randint(1, 6) for _ in range(n_dice)]

@mcp.tool()
def get_news() -> Union[int, str]:
    """Get latest news."""
    return "最新消息 Qwen4 is coming!"


# ─────────────────────────────────────────────
# 1. 股价查询工具（mock 数据，未对接真实行情接口）
# ─────────────────────────────────────────────
_STOCK_DB = {
    "AAPL": {"name": "苹果 (Apple)",      "price": 198.50, "currency": "USD"},
    "MSFT": {"name": "微软 (Microsoft)",   "price": 425.30, "currency": "USD"},
    "TSLA": {"name": "特斯拉 (Tesla)",     "price": 248.75, "currency": "USD"},
    "600519": {"name": "贵州茅台",          "price": 1685.20, "currency": "CNY"},
    "000001": {"name": "平安银行",          "price": 12.45, "currency": "CNY"},
    "00700": {"name": "腾讯控股",          "price": 385.60, "currency": "HKD"},
}

@mcp.tool()
def get_stock_price(symbol: str) -> dict:
    """查询指定股票代码的当前价格。
    symbol 参数为股票代码，例如：
    - 美股: AAPL / MSFT / TSLA
    - A 股: 600519 / 000001
    - 港股: 00700
    返回 {symbol, name, price, currency}。
    若代码不在库中会返回错误信息。"""
    info = _STOCK_DB.get(symbol.upper())
    if info is None:
        return {"symbol": symbol, "error": f"未找到股票 {symbol}，请检查代码是否正确"}
    return {"symbol": symbol.upper(), **info}


# ─────────────────────────────────────────────
# 2. 天气查询工具（mock 数据）
# ─────────────────────────────────────────────
_WEATHER_DB = {
    "北京":   {"temperature": 18, "weather": "晴",     "humidity": 35, "wind": "西北风 3级"},
    "上海":   {"temperature": 22, "weather": "多云",   "humidity": 65, "wind": "东南风 2级"},
    "深圳":   {"temperature": 27, "weather": "雷阵雨", "humidity": 80, "wind": "东南风 4级"},
    "广州":   {"temperature": 26, "weather": "多云",   "humidity": 70, "wind": "东南风 2级"},
    "杭州":   {"temperature": 21, "weather": "小雨",   "humidity": 75, "wind": "北风 2级"},
    "beijing": {"temperature": 18, "weather": "Sunny",       "humidity": 35, "wind": "NW 3"},
    "shanghai": {"temperature": 22, "weather": "Cloudy",      "humidity": 65, "wind": "SE 2"},
    "tokyo":   {"temperature": 20, "weather": "Rain",        "humidity": 78, "wind": "E 3"},
}

@mcp.tool()
def get_weather(city: str) -> dict:
    """查询指定城市的当前天气情况。
    city 参数为城市名（支持中英文），例如：北京 / 上海 / 深圳 / beijing / tokyo。
    返回 {city, temperature(摄氏度), weather, humidity(%), wind}。
    若城市不在库中会返回错误信息。"""
    info = _WEATHER_DB.get(city.strip())
    if info is None:
        return {"city": city, "error": f"未找到 {city} 的天气数据，请尝试其他城市"}
    return {"city": city, **info}


# ─────────────────────────────────────────────
# 3. 随机数生成工具
# ─────────────────────────────────────────────
@mcp.tool()
def random_number(min_val: int = 1, max_val: int = 100) -> dict:
    """在指定范围 [min_val, max_val] 内生成一个随机整数（包含两端）。
    min_val 默认 1，max_val 默认 100。
    返回 {min_val, max_val, result}。"""
    if min_val > max_val:
        return {"error": f"min_val ({min_val}) 不能大于 max_val ({max_val})"}
    return {"min_val": min_val, "max_val": max_val, "result": random.randint(min_val, max_val)}


if __name__ == "__main__":
    mcp.run(transport="sse")