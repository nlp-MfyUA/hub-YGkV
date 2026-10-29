"""开发辅助工具：本地模拟 OpenAI 兼容接口，用于在没有真实 API Key 时
验证 DeepSeekClient 的 SDK 集成路径（请求格式、响应解析、token 统计、
错误处理），避免为测试接线而消耗真实额度。

用法：
    # 终端 1：启动服务器
    python dev/mock_openai_server.py --port 8765

    # 终端 2：把 base_url 指向本地服务器，跑真实 SDK 客户端
    set LLM_BASE_URL=http://127.0.0.1:8765/v1
    set LLM_API_KEY=test-key
    python main.py ask "每个城市有多少用户"

    # 错误路径测试（Key 为 bad-key 时返回 401，模拟鉴权失败）：
    set LLM_API_KEY=bad-key
    python main.py ask "每个城市有多少用户"
"""
from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# 与真实数据无关的固定查询，仅用于验证链路
_TEST_SQL = ("SELECT city, COUNT(*) AS user_count FROM users "
             "GROUP BY city ORDER BY user_count DESC")


class Handler(BaseHTTPRequestHandler):
    server_version = "MockOpenAI/1.0"

    # ------------------------------------------------------------- 工具
    def _json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, code: str) -> None:
        self._json_response(status, {
            "error": {"message": message, "type": "invalid_request_error",
                      "param": None, "code": code}
        })

    # ------------------------------------------------------------- 路由
    def do_POST(self) -> None:  # noqa: N802 - http.server 命名约定
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._error(404, f"未知路径: {self.path}", "not_found")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error(400, "请求体不是合法 JSON", "invalid_json")
            return

        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-key":
            self._error(401, "Incorrect API key provided.", "invalid_api_key")
            return

        messages = payload.get("messages", [])
        system = next((m.get("content", "") for m in messages
                       if m.get("role") == "system"), "")
        content = self._pick_content(system)
        self._json_response(200, {
            "id": "chatcmpl-mock-server",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "deepseek-chat"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 128, "completion_tokens": 32,
                      "total_tokens": 160},
        })

    def log_message(self, fmt, *args) -> None:  # 静默默认日志
        pass

    # ------------------------------------------------------------- 内容分派
    @staticmethod
    def _pick_content(system: str) -> str:
        if "修复" in system:                       # SQL 改写
            return f"```sql\n{_TEST_SQL}\n```"
        if "数据分析专家" in system:                # SQL 生成
            return f"思路略。\n```sql\n{_TEST_SQL}\n```"
        if "数据库专家" in system:                  # Table 选择
            return json.dumps({"tables": ["users"], "reason": "测试服务器"},
                              ensure_ascii=False)
        if "数据分析师" in system:                  # 结果汇总
            return "（测试服务器）各城市用户分布已统计完成，详见结果表。"
        return "（测试服务器）未识别的任务类型"


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 OpenAI 兼容模拟服务器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), Handler)
    print(f"模拟 OpenAI 接口已启动: http://{args.host}:{args.port}/v1"
          f"（Authorization: Bearer test-key）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
