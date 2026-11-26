"""构建后验收镜像：临时容器、健康检查、真实模型双分支、普通用户和停止退出码。"""
import json
import os
from pathlib import Path
import subprocess
import time

import httpx


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, encoding="utf-8").strip()


def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError("需要 DEEPSEEK_API_KEY；该验证通常调用模型4次")
    image = "sentiment-agents:hw2"
    name = f"sentiment-hw2-verify-{os.getpid()}"
    created = False
    try:
        docker("run", "-d", "--name", name, "-p", "127.0.0.1::8000", "-e", "DEEPSEEK_API_KEY", image)
        created = True
        port = docker("inspect", "--format", '{{(index (index .NetworkSettings.Ports "8000/tcp") 0).HostPort}}', name)
        deadline = time.monotonic() + 90
        while docker("inspect", "--format", "{{.State.Health.Status}}", name) != "healthy":
            if time.monotonic() > deadline:
                raise RuntimeError("容器未就绪")
            time.sleep(1)
        results = []
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=150, trust_env=False) as client:
            assert client.get("/health").status_code == 200
            assert "情感识别与回应" in client.get("/").text
            for text, label, strategy in [
                ("今天终于完成了一个很难的任务，特别开心！", "positive", "encourage"),
                ("最近工作接连出错，我很难过，感觉压力很大。", "negative", "comfort"),
            ]:
                response = client.post("/api/chat", json={"text": text})
                assert response.status_code == 200, response.text
                data = response.json()
                assert data["analysis"]["sentiment"] == label, data
                assert data["strategy"] == strategy and data["reply"].strip(), data
                results.append(data)
            assert client.post("/api/chat", json={"text": " "}).status_code == 422
        processes = docker("top", name, "-eo", "pid,args")
        print(processes)
        assert all(f"--role {role}" in processes for role in ["frontend", "backend", "sentiment", "response"])
        assert docker("exec", name, "id", "-un") == "app"
        docker("stop", "--time", "15", name)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", name) == "0"
        record = {
            "image": image,
            "image_id": docker("image", "inspect", image, "--format", "{{.Id}}"),
            "health": "healthy",
            "user": "app",
            "four_service_processes": True,
            "stop_exit_code": 0,
            "results": results,
        }
        Path(__file__).with_name("验证结果.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False, indent=2))
        print("PASS: 镜像启动、四进程、健康检查、真实双分支、输入校验、普通用户、正常停止")
    finally:
        if created:
            subprocess.run(["docker", "rm", "-f", name], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
