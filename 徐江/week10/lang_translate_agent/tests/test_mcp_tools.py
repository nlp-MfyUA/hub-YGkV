# -*- coding: utf-8 -*-
"""
离线端到端测试: 直接调用 translation_server 暴露的 handler, 验证
基线能力(Tools/Resources/Prompts)与新增的 3 个翻译类工具。
逻辑等价于客户端走完 initialize -> tools/list -> tools/call。

运行: python tests/test_mcp_tools.py   (conda py312 环境)
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "mcp"))

import translation_server as srv_mod  # noqa: E402
from mcp.types import (  # noqa: E402
    CallToolRequestParams,
    ReadResourceRequestParams,
    GetPromptRequestParams,
)


def assert_eq(cond, msg):
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        raise SystemExit(1)


async def call_tool(name, **arguments):
    ctx = MagicMock()
    res = await srv_mod._call_tool(ctx, CallToolRequestParams(name=name, arguments=arguments))
    return json.loads(res.content[0].text)


async def main():
    ctx = MagicMock()

    print("== 1) 能力注册与工具列表 ==")
    caps = srv_mod.server.get_capabilities()
    assert_eq(caps.tools is not None, "tools 已注册")
    assert_eq(caps.resources is not None, "resources 已注册")
    assert_eq(caps.prompts is not None, "prompts 已注册")

    tools_result = await srv_mod._list_tools(ctx, None)
    names = [t.name for t in tools_result.tools]
    assert_eq(set(names) == {"get_weather", "calculate", "detect_language",
                             "translate_text", "get_language_info"},
              f"工具列表(基线2个+新增3个): {names}")

    print("== 2) 基线工具仍可用 ==")
    res = await call_tool("calculate", expression="1+2*3")
    assert_eq(res["result"] == 7, f"calculate: {res}")
    res = await call_tool("get_weather", city="成都")
    assert_eq(res["weather"] == "晴 22°C", f"get_weather: {res}")

    print("== 3) 新增工具 detect_language(语种检测) ==")
    res = await call_tool("detect_language", text="你好，世界！今天天气怎么样？")
    assert_eq(res["language"] == "zh" and res["language_name"] == "中文", f"中文检测: {res}")
    res = await call_tool("detect_language", text="Hello, world! How are you?")
    assert_eq(res["language"] == "en" and res["language_name"] == "英语", f"英语检测: {res}")
    res = await call_tool("detect_language", text="こんにちは、世界")
    assert_eq(res["language"] == "ja" and res["language_name"] == "日语", f"日语检测: {res}")
    res = await call_tool("detect_language", text="Bonjour, le monde! Merci beaucoup.")
    assert_eq(res["language"] == "fr" and res["language_name"] == "法语", f"法语检测: {res}")
    res = await call_tool("detect_language", text="   ")
    assert_eq(res["language"] == "unknown", f"空文本检测: {res}")

    print("== 4) 新增工具 get_language_info(语言元数据) ==")
    res = await call_tool("get_language_info", language="zh")
    assert_eq(res["found"] and res["name_zh"] == "中文", f"按代码查询: {res}")
    res = await call_tool("get_language_info", language="日语")
    assert_eq(res["found"] and res["language"] == "ja", f"按中文名查询: {res}")
    res = await call_tool("get_language_info", language="French")
    assert_eq(res["found"] and res["language"] == "fr", f"按英文名查询: {res}")
    res = await call_tool("get_language_info", language="klingon")
    assert_eq(res["found"] is False and "supported" in res, f"未知语言查询: {res}")

    print("== 5) 新增工具 translate_text(翻译, 未配置密钥时优雅报错) ==")
    saved_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        res = await call_tool("translate_text", text="你好", target_language="en")
        assert_eq("OPENAI_API_KEY" in res.get("error", ""), f"无密钥报错: {res}")
        res = await call_tool("translate_text", text="你好", target_language="克林贡语")
        assert_eq("目标语言" in res.get("error", ""), f"非法目标语言报错: {res}")
    finally:
        if saved_key is not None:
            os.environ["OPENAI_API_KEY"] = saved_key
    res = await call_tool("translate_text", text="", target_language="en")
    assert_eq("text" in res.get("error", ""), f"空文本报错: {res}")

    print("== 6) 基线 Resources / Prompts 仍可用 ==")
    resources_result = await srv_mod._list_resources(ctx, None)
    uris = [r.uri for r in resources_result.resources]
    assert_eq("config://app" in uris, f"资源列表: {uris}")
    res = await srv_mod._read_resource(ctx, ReadResourceRequestParams(uri="greeting://元宝"))
    assert_eq("元宝" in res.contents[0].text, f"read greeting: {res.contents[0].text}")
    prompts_result = await srv_mod._list_prompts(ctx, None)
    pnames = [p.name for p in prompts_result.prompts]
    assert_eq(set(pnames) == {"code_review", "translate"}, f"提示词: {pnames}")

    print("\n🎉 全部测试通过！基线能力 + 3 个新增翻译类工具均正常工作。")
    print("💡 提示: 配置 .env 中的 OPENAI_API_KEY 后, translate_text 将真实调用大模型翻译。")


if __name__ == "__main__":
    asyncio.run(main())
