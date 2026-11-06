# -*- coding: utf-8 -*-
"""
真实 stdio 测试: 以子进程启动 python mcp/translation_server.py, 通过标准输入输出
发送 JSON-RPC 消息, 模拟 OpenAI Agents SDK 等客户端的真实握手流程。
验证: initialize -> tools/list -> tools/call(含新增翻译类工具)。

运行: python tests/test_stdio.py   (conda py312 环境)
"""
import asyncio
import json
import sys
from pathlib import Path

SERVER_SCRIPT = str(Path(__file__).resolve().parent.parent / "mcp" / "translation_server.py")


class StdioClient:
    def __init__(self, proc):
        self.proc = proc
        self.next_id = 1

    async def request(self, method, params=None):
        req = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.next_id += 1
        self.proc.stdin.write((json.dumps(req) + "\n").encode())
        await self.proc.stdin.drain()
        line = await self.proc.stdout.readline()
        return json.loads(line.decode())

    async def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()


async def main():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, SERVER_SCRIPT,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    client = StdioClient(proc)

    def check(cond, msg):
        print(f"  {'✅' if cond else '❌'} {msg}")
        if not cond:
            raise SystemExit(1)

    try:
        # 1) initialize 握手
        resp = await client.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        })
        check("result" in resp,
              f"initialize 握手成功: serverInfo={resp.get('result', {}).get('serverInfo')}")

        # 2) initialized 通知
        await client.notify("notifications/initialized")

        # 3) tools/list: 基线 2 个 + 新增 3 个翻译类工具
        resp = await client.request("tools/list")
        names = [t["name"] for t in resp["result"]["tools"]]
        check(set(names) == {"get_weather", "calculate", "detect_language",
                             "translate_text", "get_language_info"},
              f"tools/list: {names}")

        # 4) tools/call: 新增 detect_language
        resp = await client.request("tools/call",
                                    {"name": "detect_language", "arguments": {"text": "你好，世界"}})
        text = resp["result"]["content"][0]["text"]
        payload = json.loads(text)
        check(payload.get("language") == "zh", f"tools/call detect_language: {text}")

        # 5) tools/call: 新增 get_language_info
        resp = await client.request("tools/call",
                                    {"name": "get_language_info", "arguments": {"language": "日语"}})
        text = resp["result"]["content"][0]["text"]
        payload = json.loads(text)
        check(payload.get("language") == "ja", f"tools/call get_language_info: {text}")

        # 6) tools/call: 基线 calculate 仍然可用
        resp = await client.request("tools/call",
                                    {"name": "calculate", "arguments": {"expression": "(2+3)/4"}})
        text = resp["result"]["content"][0]["text"]
        check("1.25" in text, f"tools/call calculate: {text}")

        print("\n🎉 真实 stdio JSON-RPC 握手测试通过！Server 可被客户端以子进程拉起。")
    finally:
        proc.terminate()
        await proc.wait()


if __name__ == "__main__":
    asyncio.run(main())
