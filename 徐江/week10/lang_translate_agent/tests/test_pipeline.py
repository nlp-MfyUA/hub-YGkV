# -*- coding: utf-8 -*-
"""
主流程编排测试: mock 掉 Runner(不真实调用大模型), 验证
  1. MCP Server 能被 OpenAI Agents SDK 以子进程方式真实拉起;
  2. 语种路由规则正确(中文→英文, 其他语言→中文);
  3. 最终输出严格为 {"query_input", "language", "result"} 三字段 JSON;
  4. _extract_json 对 ```json 代码块等输出的容错解析。

运行: python tests/test_pipeline.py   (conda py312 环境)
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import main as app  # noqa: E402


class _FakeResult:
    def __init__(self, final_output):
        self.final_output = final_output


def _make_fake_runner(detected_code, detected_name, translated_text):
    async def _fake_run(agent, user_input, **kwargs):
        if agent.name == "LanguageDetector":
            return _FakeResult(f'```json\n{{"language": "{detected_code}", '
                               f'"language_name": "{detected_name}"}}\n```')
        # Translator: 校验传入的提示词中包含路由后的目标语言
        assert "目标语言" in user_input
        return _FakeResult(f'"{translated_text}"')

    runner = MagicMock()
    runner.run = AsyncMock(side_effect=_fake_run)
    return runner


async def run_case(query, code, name, text, expect_target_hint):
    fake_runner = _make_fake_runner(code, name, text)
    with patch.object(app, "Runner", fake_runner):
        out = await app.run_pipeline(query)
    assert set(out.keys()) == {"query_input", "language", "result"}, f"字段不符合规范: {out}"
    assert out["query_input"] == query, f"query_input 不符: {out}"
    assert out["language"] == name, f"language 不符: {out}"
    assert out["result"] == text, f"result 不符: {out}"
    # 校验翻译 Agent 收到的输入中包含正确的目标语言路由
    translator_calls = [c for c in fake_runner.run.call_args_list
                        if c.args[0].name == "Translator"]
    assert len(translator_calls) == 1, "Translator 应被调用一次"
    assert expect_target_hint in translator_calls[0].args[1], \
        f"路由提示词缺少 {expect_target_hint}: {translator_calls[0].args[1]}"
    print(f"  ✅ [{code}] {query!r} -> language={name!r}, result={text!r}, 目标={expect_target_hint}")


async def main():
    print("== 主流程编排测试(Runner 已 mock, MCP Server 真实拉起) ==")
    await run_case("你好，世界", "zh", "中文", "Hello, world", "英文(en)")
    await run_case("Hello, world", "en", "英语", "你好，世界", "中文(zh)")
    await run_case("こんにちは、世界", "ja", "日语", "你好，世界", "中文(zh)")
    await run_case("Bonjour", "fr", "法语", "你好", "中文(zh)")

    print("== _extract_json 容错解析 ==")
    assert app._extract_json('{"language": "zh"}')["language"] == "zh"
    assert app._extract_json('```json\n{"a": 1}\n```')["a"] == 1
    assert app._extract_json('前缀文字 {"a": 2} 后缀文字')["a"] == 2
    print("  ✅ 纯 JSON / 代码块 / 前后缀文字 三种形态均可解析")

    print("\n🎉 主流程编排测试全部通过！")


if __name__ == "__main__":
    asyncio.run(main())
