"""四个真实 HTTP 进程的集成验证。默认使用本地假模型；--live 调用 DeepSeek。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx


class FakeModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = body["messages"][-1]["content"]
        if isinstance(user, list):
            user = "".join(part.get("text", "") for part in user)
        if body.get("response_format", {}).get("type") == "json_object":
            label = "negative" if "难过" in user else "positive"
            content = json.dumps({"sentiment": label, "reason": "测试模型输出"}, ensure_ascii=False)
        else:
            content = "先休息一下，试着将眼前的任务拆成一小步。" if 'negative' in user else "完成任务带来的满足感很珍贵，可以记录这次的经验。"
        data = json.dumps({"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
                           "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                           "message": {"role": "assistant", "content": content}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def free_ports():
    sockets = []
    try:
        for _ in range(4):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def verify(framework, live):
    root = Path(__file__).resolve().parent
    ports = dict(zip(["frontend", "backend", "sentiment", "response"], free_ports()))
    env = os.environ.copy()
    server = None
    if not live:
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env["DEEPSEEK_API_KEY"] = "local-test-key"
        env["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{server.server_port}/v1"
    elif not env.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("--live 需要 DEEPSEEK_API_KEY")
    for role in ("backend", "sentiment", "response"):
        env[f"{role.upper()}_URL"] = f"http://127.0.0.1:{ports[role]}"
    processes = []
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as logs:
        try:
            for role, port in ports.items():
                processes.append(subprocess.Popen([
                    sys.executable, "-m", "common.service", "--framework", framework,
                    "--role", role, "--port", str(port),
                ], cwd=root, env=env, stdout=logs, stderr=logs))
            with httpx.Client(base_url=f"http://127.0.0.1:{ports['frontend']}", timeout=150, trust_env=False) as client:
                deadline = time.monotonic() + 60
                while True:
                    try:
                        health = client.get("/health", timeout=2)
                        if health.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if any(p.poll() is not None for p in processes) or time.monotonic() > deadline:
                        raise RuntimeError("服务启动失败")
                    time.sleep(0.3)
                assert "情感识别与回应" in client.get("/").text
                for text, expected, strategy in [
                    ("今天终于完成了一个很难的任务，特别开心！", "positive", "encourage"),
                    ("最近工作接连出错，我很难过，感觉压力很大。", "negative", "comfort"),
                ]:
                    response = client.post("/api/chat", json={"text": text})
                    assert response.status_code == 200, response.text
                    result = response.json()
                    assert result["analysis"]["sentiment"] == expected, result
                    assert result["strategy"] == strategy, result
                    assert result["framework"] == framework and result["reply"].strip(), result
                    print(json.dumps({"mode": "live" if live else "mock", **result}, ensure_ascii=False))
                for invalid in [{"text": "   "}, {"text": "a" * 2001}, {}, {"text": 123}]:
                    assert client.post("/api/chat", json=invalid).status_code == 422
                # 停止进程2，验证故障沿后端和前端传播，不返回伪造成功结果。
                processes[3].terminate()
                processes[3].wait(timeout=10)
                assert client.get("/health").status_code == 502
                if not live:
                    assert client.post("/api/chat", json={"text": "开心"}).status_code == 502
            print(f"PASS {framework}: 四进程、双分支、输入校验、下游故障传播")
        except Exception:
            logs.seek(0)
            # 服务日志只包含访问行和异常类型，不包含密钥。
            print(logs.read(), file=sys.stderr)
            raise
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if server:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--framework", choices=["langgraph", "openai-agents", "all"], default="all")
    args = parser.parse_args()
    for framework in (["langgraph", "openai-agents"] if args.framework == "all" else [args.framework]):
        verify(framework, args.live)
