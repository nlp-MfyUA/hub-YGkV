"""
命令行冒烟测试：不启动浏览器，直接验证 FastAPI + LangGraph 链路。

    python smoke_test.py

会依次检查：
    1. GET  /api/health           模型 / 数据库 / 表数量
    2. POST /api/chat             非流式接口返回完整结果
    3. POST /api/chat/stream      流式接口逐节点推送，并验证多轮记忆
"""
from __future__ import annotations

import json
import sys
import uuid

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402


def print_stage(event: dict) -> None:
    detail = event.get("detail") or ""
    error = event.get("error")
    suffix = f"  [{error}]" if error and error not in detail else ""
    print(
        f"    [{event.get('name')}]"
        + (f" {detail}" if detail else "")
        + f"  ({event.get('elapsed', 0):.2f}s){suffix}"
    )


def ask_stream(client: TestClient, question: str, session_id: str) -> dict:
    print(f"\n>>> {question}")
    final: dict | None = None

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": question, "session_id": session_id},
    ) as response:
        assert response.status_code == 200, response.text
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event.get("type") == "stage":
                print_stage(event)
            elif event.get("type") == "final":
                final = event
            elif event.get("type") == "error":
                raise AssertionError(event.get("message"))

    assert final is not None, "没有收到 final 事件"
    print(f"回答：{final['answer']}")
    print(f"SQL ：{final['sql']}")
    print(f"结果：{len(final['rows'])} 行 / 选表 {', '.join(final['tables'])}")
    return final


def main() -> None:
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"

    with TestClient(app) as client:
        print("=" * 68)
        print("1. 健康检查")
        print("=" * 68)
        health = client.get("/api/health").json()
        print(json.dumps(health, ensure_ascii=False, indent=2))
        assert health["ok"], health.get("error")

        print("\n" + "=" * 68)
        print("2. 非流式接口 /api/chat")
        print("=" * 68)
        response = client.post(
            "/api/chat",
            json={
                "message": "每位员工负责的客户数量是多少？按客户数排序。",
                "session_id": session_id + "-basic",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        print(f"回答：{data['answer']}")
        print(f"SQL ：{data['sql']}")
        print(
            "阶段："
            + " → ".join(
                f"{stage['name']}({stage['elapsed']:.2f}s)" for stage in data["stages"]
            )
        )
        assert data["ok"] and data["rows"][0]

        print("\n" + "=" * 68)
        print("3. 流式接口 /api/chat/stream + 多轮记忆")
        print("=" * 68)
        first = ask_stream(client, "Rock 类型的歌曲一共有多少首？", session_id)
        second = ask_stream(client, "那 Pop 呢？", session_id)

        assert first["rows"][0] and second["rows"][0]
        assert "Pop" in second["sql"], second["sql"]
        print("\n冒烟测试通过：非流式 / 流式 / 多轮记忆均正常。")


if __name__ == "__main__":
    main()
