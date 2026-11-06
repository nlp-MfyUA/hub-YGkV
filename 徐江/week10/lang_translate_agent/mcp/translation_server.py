# -*- coding: utf-8 -*-
"""
MCP Server: 翻译工具服务器 (stdio 通信)
基于官方 Python SDK: mcp >= 2.0 (本机 conda py312 环境为 mcp 2.1.1)

基线代码: 「2-兼容OpenAI-Agent」课程示例 mcp_server_demo/mcp_server.py
         (Server(..., on_list_tools=..., on_call_tool=...) 构造函数回调注册风格)

本文件在基线基础上新增 3 个「翻译类」MCP 工具(由大模型设计生成):
  - detect_language(text)                 检测文本语种(本地 Unicode 规则, 无需大模型)
  - translate_text(text, src, tgt)        翻译文本(内部调用 OpenAI 兼容大模型接口)
  - get_language_info(language)           查询语言元数据(代码/中英文名/语系/书写系统/使用地区)

保留基线的全部能力:
  - Tools:     get_weather(city), calculate(expression)
  - Resources: config://app, greeting://{name}
  - Prompts:   code_review(code), translate(text, language)

运行:
  python translation_server.py            # 由客户端(如 OpenAI Agents SDK)以子进程拉起, 走 stdio
  python tests/test_mcp_tools.py          # 离线端到端测试(直接调用 handler)
  python tests/test_stdio.py              # 真实 stdio JSON-RPC 握手测试
"""
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    Resource,
    Prompt,
    TextContent,
    GetPromptResult,
    PromptMessage,
    CallToolResult,
    ReadResourceResult,
    TextResourceContents,
    ListToolsResult,
    ListResourcesResult,
    ListPromptsResult,
)

# 加载项目根目录 .env(大模型密钥等), 便于子进程独立运行
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ----------------------------------------------------------------------
# 新增: 语种元数据表(供 detect_language / get_language_info / translate_text 共用)
# ----------------------------------------------------------------------
LANGUAGES: dict[str, dict[str, Any]] = {
    "zh": {"name_zh": "中文", "name_en": "Chinese", "family": "汉藏语系",
           "script": "汉字", "regions": "中国、新加坡、马来西亚等", "speakers": "约 14 亿"},
    "en": {"name_zh": "英语", "name_en": "English", "family": "印欧语系·日耳曼语族",
           "script": "拉丁字母", "regions": "美国、英国、印度、澳大利亚等", "speakers": "约 15 亿"},
    "ja": {"name_zh": "日语", "name_en": "Japanese", "family": "日本语系(争议)",
           "script": "假名+汉字", "regions": "日本", "speakers": "约 1.25 亿"},
    "ko": {"name_zh": "韩语", "name_en": "Korean", "family": "朝鲜语系",
           "script": "谚文", "regions": "韩国、朝鲜", "speakers": "约 7700 万"},
    "fr": {"name_zh": "法语", "name_en": "French", "family": "印欧语系·罗曼语族",
           "script": "拉丁字母", "regions": "法国、加拿大、比利时等", "speakers": "约 3 亿"},
    "de": {"name_zh": "德语", "name_en": "German", "family": "印欧语系·日耳曼语族",
           "script": "拉丁字母", "regions": "德国、奥地利、瑞士等", "speakers": "约 1.3 亿"},
    "es": {"name_zh": "西班牙语", "name_en": "Spanish", "family": "印欧语系·罗曼语族",
           "script": "拉丁字母", "regions": "西班牙、墨西哥、阿根廷等", "speakers": "约 6 亿"},
    "pt": {"name_zh": "葡萄牙语", "name_en": "Portuguese", "family": "印欧语系·罗曼语族",
           "script": "拉丁字母", "regions": "巴西、葡萄牙、安哥拉等", "speakers": "约 2.6 亿"},
    "it": {"name_zh": "意大利语", "name_en": "Italian", "family": "印欧语系·罗曼语族",
           "script": "拉丁字母", "regions": "意大利、瑞士等", "speakers": "约 8500 万"},
    "ru": {"name_zh": "俄语", "name_en": "Russian", "family": "印欧语系·斯拉夫语族",
           "script": "西里尔字母", "regions": "俄罗斯、哈萨克斯坦等", "speakers": "约 2.5 亿"},
    "ar": {"name_zh": "阿拉伯语", "name_en": "Arabic", "family": "闪含语系",
           "script": "阿拉伯字母", "regions": "沙特、埃及、阿联酋等", "speakers": "约 4 亿"},
    "th": {"name_zh": "泰语", "name_en": "Thai", "family": "壮侗语系",
           "script": "泰文", "regions": "泰国", "speakers": "约 6000 万"},
    "hi": {"name_zh": "印地语", "name_en": "Hindi", "family": "印欧语系·印度-雅利安语族",
           "script": "天城文", "regions": "印度", "speakers": "约 6 亿"},
    "he": {"name_zh": "希伯来语", "name_en": "Hebrew", "family": "闪含语系",
           "script": "希伯来字母", "regions": "以色列", "speakers": "约 900 万"},
    "el": {"name_zh": "希腊语", "name_en": "Greek", "family": "印欧语系·希腊语族",
           "script": "希腊字母", "regions": "希腊、塞浦路斯", "speakers": "约 1300 万"},
}

# Unicode 区段 -> 语言代码(按优先级排列: 假名/谚文需先于汉字判断)
_SCRIPT_RANGES: list[tuple[str, list[tuple[int, int]]]] = [
    ("ja", [(0x3040, 0x309F), (0x30A0, 0x30FF)]),            # 平假名 / 片假名 → 日语
    ("ko", [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)]),  # 谚文 → 韩语
    ("zh", [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF)]),  # CJK 汉字 → 中文
    ("ru", [(0x0400, 0x04FF)]),                                # 西里尔字母 → 俄语
    ("ar", [(0x0600, 0x06FF), (0x0750, 0x077F)]),              # 阿拉伯字母 → 阿拉伯语
    ("th", [(0x0E00, 0x0E7F)]),                                # 泰文 → 泰语
    ("he", [(0x0590, 0x05FF)]),                                # 希伯来字母 → 希伯来语
    ("hi", [(0x0900, 0x097F)]),                                # 天城文 → 印地语
    ("el", [(0x0370, 0x03FF)]),                                # 希腊字母 → 希腊语
]

# 拉丁字母语言的停用词投票表(区分英/法/德/西/葡/意)
_LATIN_HINTS: dict[str, set[str]] = {
    "en": {"the", "be", "is", "are", "was", "and", "or", "of", "to", "in", "on",
           "it", "you", "that", "this", "for", "with", "hello", "world", "what", "how"},
    "fr": {"le", "la", "les", "un", "une", "des", "est", "et", "ou", "que", "qui",
           "pour", "dans", "bonjour", "merci", "avec", "pas"},
    "de": {"der", "die", "das", "ist", "und", "oder", "ein", "eine", "einem",
           "hallo", "danke", "mit", "nicht", "sie", "ich"},
    "es": {"el", "la", "los", "las", "un", "una", "es", "son", "que", "por",
           "para", "hola", "gracias", "con", "muy"},
    "pt": {"o", "a", "os", "as", "um", "uma", "é", "são", "que", "para",
           "olá", "obrigado", "com", "não"},
    "it": {"il", "la", "lo", "gli", "le", "un", "una", "è", "sono", "che",
           "per", "ciao", "grazie", "con", "non"},
}


def _resolve_language(value: str) -> str | None:
    """把用户传入的语言代码/中英文名统一解析为 ISO 639-1 代码, 失败返回 None。"""
    if not value:
        return None
    v = value.strip()
    if v.lower() in LANGUAGES:
        return v.lower()
    for code, meta in LANGUAGES.items():
        if v in (meta["name_zh"], meta["name_en"], meta["name_en"].lower()):
            return code
    return None


def _lang_name_zh(code: str) -> str:
    return LANGUAGES.get(code, {}).get("name_zh", "未知语言")


def _detect_language(text: str) -> dict[str, Any]:
    """本地规则语种检测: Unicode 区段优先, 拉丁字母走停用词投票, 均不中按未知处理。"""
    if not text or not text.strip():
        return {"language": "unknown", "language_name": "未知", "confidence": 0.0, "script": "无"}

    total = len([c for c in text if not c.isspace()])
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for code, ranges in _SCRIPT_RANGES:
            if any(lo <= cp <= hi for lo, hi in ranges):
                counts[code] = counts.get(code, 0) + 1

    if counts:
        code = max(counts, key=lambda k: counts[k])
        ratio = counts[code] / max(total, 1)
        confidence = 0.95 if ratio > 0.3 else 0.85
        return {"language": code, "language_name": _lang_name_zh(code),
                "confidence": confidence, "script": LANGUAGES[code]["script"]}

    if re.search(r"[a-zA-Z]", text):
        words = set(re.findall(r"[a-zA-Z']+", text.lower()))
        scores = {code: len(words & hints) for code, hints in _LATIN_HINTS.items()}
        best = max(scores, key=lambda k: scores[k])
        if scores[best] > 0:
            return {"language": best, "language_name": _lang_name_zh(best),
                    "confidence": 0.9, "script": "拉丁字母"}
        # 拉丁字母但无任何停用词命中, 兜底按英语(置信度较低)
        return {"language": "en", "language_name": "英语",
                "confidence": 0.6, "script": "拉丁字母"}

    return {"language": "unknown", "language_name": "未知", "confidence": 0.0, "script": "未知"}


async def _llm_translate(text: str, src_code: str, tgt_code: str) -> tuple[str | None, str | None]:
    """调用 OpenAI 兼容大模型接口完成翻译, 返回 (译文, 错误信息)。"""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, "未配置 OPENAI_API_KEY, 无法调用大模型翻译(请在 .env 中配置)"
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL") or None)
        model = os.environ.get("TRANSLATE_MODEL", "gpt-4o-mini")
        src_name = _lang_name_zh(src_code) if src_code in LANGUAGES else src_code
        tgt_name = _lang_name_zh(tgt_code) if tgt_code in LANGUAGES else tgt_code
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": (
                f"你是专业翻译。请将以下{src_name}文本翻译成{tgt_name}。"
                f"要求：只输出译文本身，不要输出解释、注释或任何额外格式。\n\n{text}"
            )}],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip(), None
    except Exception as exc:  # 网络/鉴权/限流等
        return None, f"大模型翻译调用失败: {exc}"


# ----------------------------------------------------------------------
# 工具 / 资源 / 提示词的 数据 与 handler
# ----------------------------------------------------------------------
def _tools() -> list[Tool]:
    return [
        # ---- 基线原有工具 ----
        Tool(
            name="get_weather",
            description="获取指定城市的天气（示例为模拟数据，可替换为真实 API）",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，如 成都"}
                },
                "required": ["city"],
            },
        ),
        Tool(
            name="calculate",
            description="计算数学表达式，如 1+2*3、(2+3)/4",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式"}
                },
                "required": ["expression"],
            },
        ),
        # ---- 新增: 3 个翻译类工具(需求二) ----
        Tool(
            name="detect_language",
            description="检测一段文本的语种。基于本地 Unicode 字符规则 + 拉丁语言停用词投票，无需调用大模型。返回 ISO 639-1 语言代码、中文语言名、置信度与书写系统。",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待检测语种的文本"}
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="translate_text",
            description="翻译文本。source_language 支持 auto(自动检测)或语言代码/名称；按规则中文↔英文互译时可指定具体目标语言。内部调用 OpenAI 兼容大模型接口完成翻译。",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待翻译的文本"},
                    "source_language": {"type": "string",
                                        "description": "源语言：auto 或语言代码/名称，如 zh、中文、English"},
                    "target_language": {"type": "string",
                                        "description": "目标语言代码/名称，如 en、英文、zh、中文"},
                },
                "required": ["text", "target_language"],
            },
        ),
        Tool(
            name="get_language_info",
            description="查询语言元数据：语言代码、中/英文名称、语系、书写系统、主要使用地区、使用人数。支持按代码(zh)、中文名(中文)或英文名(Chinese)查询。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "语言代码/中文名/英文名，如 zh、日语、French"}
                },
                "required": ["language"],
            },
        ),
    ]


async def _call_tool(context, params) -> Any:
    # 注意: 回调签名为 (context, params), params 是 typed 对象
    name = params.name
    arguments = params.arguments or {}
    if name == "get_weather":
        city = arguments.get("city", "")
        mock = {"成都": "晴 22°C", "北京": "多云 18°C", "深圳": "阵雨 28°C"}
        result = mock.get(city, f"{city} 未知城市，默认 晴 20°C")
        return CallToolResult(content=[TextContent(type="text", text=json.dumps({"city": city, "weather": result}, ensure_ascii=False))])
    if name == "calculate":
        expr = arguments.get("expression", "")
        allowed = set("0123456789+-*/(). ")
        if not set(expr).issubset(allowed):
            return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": "非法字符"}, ensure_ascii=False))])
        value = eval(expr, {"__builtins__": {}}, {})
        return CallToolResult(content=[TextContent(type="text", text=json.dumps({"expression": expr, "result": value}, ensure_ascii=False))])

    # ---- 新增: 3 个翻译类工具的实现 ----
    if name == "detect_language":
        text = arguments.get("text", "")
        return CallToolResult(content=[TextContent(
            type="text", text=json.dumps(_detect_language(text), ensure_ascii=False))])

    if name == "get_language_info":
        query = arguments.get("language", "")
        code = _resolve_language(query)
        if code is None:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(
                {"found": False, "query": query, "supported": sorted(LANGUAGES.keys())},
                ensure_ascii=False))])
        info = {"found": True, "language": code, **LANGUAGES[code]}
        return CallToolResult(content=[TextContent(
            type="text", text=json.dumps(info, ensure_ascii=False))])

    if name == "translate_text":
        text = arguments.get("text", "")
        source = arguments.get("source_language", "auto") or "auto"
        target = arguments.get("target_language", "")
        tgt_code = _resolve_language(target)
        if not text:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(
                {"error": "text 不能为空"}, ensure_ascii=False))])
        if tgt_code is None:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(
                {"error": f"无法识别的目标语言: {target}", "supported": sorted(LANGUAGES.keys())},
                ensure_ascii=False))])
        # 源语言 auto 时先用本地规则检测
        if source.strip().lower() == "auto":
            src_code = _detect_language(text)["language"]
        else:
            src_code = _resolve_language(source)
            if src_code is None:
                src_code = _detect_language(text)["language"]
        translated, err = await _llm_translate(text, src_code, tgt_code)
        if err:
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(
                {"error": err, "source_language": src_code, "target_language": tgt_code},
                ensure_ascii=False))])
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(
            {"source_language": src_code, "target_language": tgt_code,
             "original_text": text, "translated_text": translated,
             "model": os.environ.get("TRANSLATE_MODEL", "gpt-4o-mini")},
            ensure_ascii=False))])

    return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False))])


def _resources() -> list[Resource]:
    return [
        Resource(
            uri="config://app",
            name="应用配置",
            description="应用的全局配置 (JSON)",
            mimeType="application/json",
        ),
        Resource(
            uri="greeting://{name}",
            name="动态问候",
            description="根据 name 返回问候语（支持模板参数）",
            mimeType="text/plain",
        ),
    ]


async def _read_resource(context, params) -> Any:
    uri = params.uri
    if uri == "config://app":
        cfg = {"version": "1.0.0", "theme": "dark", "language": "zh-CN"}
        return ReadResourceResult(contents=[TextResourceContents(
            uri=uri, mimeType="application/json",
            text=json.dumps(cfg, ensure_ascii=False))])
    if uri.startswith("greeting://"):
        name = uri.split("://", 1)[1] or "陌生人"
        return ReadResourceResult(contents=[TextResourceContents(
            uri=uri, mimeType="text/plain",
            text=f"你好, {name}！欢迎使用 translation-mcp-server。")])
    raise ValueError(f"未知资源: {uri}")


def _prompts() -> list[Prompt]:
    return [
        Prompt(
            name="code_review",
            description="对给定代码做评审",
            arguments=[{"name": "code", "description": "待评审的代码", "required": True}],
        ),
        Prompt(
            name="translate",
            description="将文本翻译成目标语言",
            arguments=[
                {"name": "text", "description": "待翻译文本", "required": True},
                {"name": "language", "description": "目标语言，如 英文", "required": True},
            ],
        ),
    ]


async def _get_prompt(context, params) -> GetPromptResult:
    name = params.name
    arguments = params.arguments or {}
    if name == "code_review":
        code = arguments.get("code", "")
        return GetPromptResult(
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"请评审以下代码：\n```\n{code}\n```"))]
        )
    if name == "translate":
        text = arguments.get("text", "")
        language = arguments.get("language", "英文")
        return GetPromptResult(
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"请将以下文本翻译成{language}：\n\n{text}"))]
        )
    raise ValueError(f"未知提示词: {name}")


# ----------------------------------------------------------------------
# 创建 Server 实例 (构造函数回调注册)
# 同时把回调暴露为模块级变量, 方便测试/复用直接调用。
# ----------------------------------------------------------------------
async def _list_tools(context, params):
    return ListToolsResult(tools=_tools())


async def _list_resources(context, params):
    return ListResourcesResult(resources=_resources())


async def _list_prompts(context, params):
    return ListPromptsResult(prompts=_prompts())


server = Server(
    "translation-mcp-server",
    on_list_tools=_list_tools,
    on_call_tool=_call_tool,
    on_list_resources=_list_resources,
    on_read_resource=_read_resource,
    on_list_prompts=_list_prompts,
    on_get_prompt=_get_prompt,
)


# ----------------------------------------------------------------------
# 入口: 通过 stdio 启动
# ----------------------------------------------------------------------
async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
