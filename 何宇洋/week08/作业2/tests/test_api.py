import time

import pytest
from fastapi.testclient import TestClient

from research_assistant.api import create_app
from research_assistant.config import Settings
from research_assistant.engine import ResearchEngine
from .fakes import FakeLLM, FakeReader, FakeSearch


def configured(tmp_path, key="fake-key", delay=0.02):
    settings = Settings(api_key=key, output_dir=tmp_path)
    engine = ResearchEngine(settings, FakeLLM(delay=delay), FakeSearch(), FakeReader())
    return create_app(settings, engine)


def await_job(client, job_id):
    for _ in range(200):
        status = client.get(f"/research/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.01)
    raise AssertionError("任务未完成")


def test_api_lifecycle_and_single_task(tmp_path):
    with TestClient(configured(tmp_path)) as client:
        assert client.get("/health").json()["status"] == "ready"
        response = client.post("/research", json={"topic": "测试 API 研究"})
        assert response.status_code == 202
        job_id = response.json()["id"]
        assert client.get(f"/research/{job_id}/report").status_code == 409
        assert client.post("/research", json={"topic": "第二个任务"}).status_code == 409
        status = await_job(client, job_id)
        assert status["status"] == "completed"
        assert status["remaining_seconds"] >= 0
        assert client.get(f"/research/{job_id}/events").json()["events"]
        report = client.get(f"/research/{job_id}/report")
        assert report.status_code == 200
        assert "attachment" in report.headers["content-disposition"]
        markdown = client.get(f"/research/{job_id}/report?format=markdown")
        assert "## 关键结论" in markdown.text
        assert "text/markdown" in markdown.headers["content-type"]
        assert client.post("/research", json={"topic": "后续任务"}).status_code == 202


def test_missing_key_and_not_found(tmp_path):
    with TestClient(configured(tmp_path, key="")) as client:
        assert client.get("/health").json()["status"] == "not_ready"
        response = client.post("/research", json={"topic": "主题"})
        assert response.status_code == 503
        assert "DEEPSEEK_API_KEY" in response.text
        for path in ["/research/missing", "/research/missing/events", "/research/missing/report"]:
            assert client.get(path).status_code == 404


@pytest.mark.parametrize("overrides", [
    {"topic": "  "}, {"max_rounds": 3}, {"max_pages": 9}, {"timeout_seconds": 301},
    {"timeout_seconds": 0}, {"max_pages": True}, {"unexpected": 1}, {"max_rounds": "2"},
])
def test_input_validation(tmp_path, overrides):
    with TestClient(configured(tmp_path)) as client:
        assert client.post("/research", json={"topic": "有效主题", **overrides}).status_code == 422


def test_restart_forgets_jobs_but_keeps_reports(tmp_path):
    with TestClient(configured(tmp_path)) as client:
        job_id = client.post("/research", json={"topic": "重启测试"}).json()["id"]
        await_job(client, job_id)
    with TestClient(configured(tmp_path)) as client:
        assert client.get(f"/research/{job_id}").status_code == 404
    assert (tmp_path / job_id / "report.md").exists()


def test_secret_never_returned_or_saved(tmp_path):
    secret = "fake-secret-do-not-leak"
    with TestClient(configured(tmp_path, key=secret)) as client:
        job_id = client.post("/research", json={"topic": f"测试 {secret}"}).json()["id"]
        await_job(client, job_id)
        for path in ["/health", f"/research/{job_id}", f"/research/{job_id}/events", f"/research/{job_id}/report"]:
            assert secret not in client.get(path).text
    for file in (tmp_path / job_id).iterdir():
        assert secret not in file.read_text(encoding="utf-8")
