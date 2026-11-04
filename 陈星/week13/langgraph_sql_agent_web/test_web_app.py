"""FastAPI 网页接口离线测试：注入假图验证 API 契约，不调用 LLM。"""
from __future__ import annotations
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from web_app import app


class FakeGraph:
    def invoke(self, input_state, config=None):
        return self._final(input_state)

    def stream(self, input_state, config=None, stream_mode=None):
        yield dict(input_state)
        yield {
            **input_state,
            "trace": ["select_tables: ['albums']"],
        }
        yield self._final(input_state)

    def _final(self, state):
        return {
            **state,
            "tables": ["albums"],
            "sql": "SELECT COUNT(*) AS album_count FROM albums",
            "answer": "数据库里共有 347 张专辑。",
            "rows": [["347"]],
            "columns": ["album_count"],
            "shown_rows": 1,
            "repair_count": 0,
            "trace": ["select_tables: ['albums']", "execute_sql: 成功"],
            "error": "",
        }


class WebAPITest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.patcher = patch("web_app.get_graph", return_value=FakeGraph())
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_homepage(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("QueryLab", response.text)
        self.assertIn("html", response.headers["content-type"])

    def test_static_js(self):
        response = self.client.get("/static/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/chat/stream", response.text)

    def test_config(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["mode"], ("mock", "llm"))

    def test_json_chat(self):
        response = self.client.post(
            "/api/chat", json={"message": "多少张专辑？"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["rows"], [["347"]])
        self.assertEqual(data["columns"], ["album_count"])
        self.assertEqual(data["shown_rows"], 1)

    def test_sse_stream(self):
        response = self.client.post(
            "/api/chat/stream", json={"message": "多少张专辑？"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("event: progress", response.text)
        self.assertIn("event: result", response.text)
        self.assertIn("347", response.text)

    def test_empty_question(self):
        response = self.client.post("/api/chat", json={"message": "   "})
        self.assertEqual(response.status_code, 422)

    def test_overlong_question(self):
        response = self.client.post(
            "/api/chat", json={"message": "a" * 501}
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
