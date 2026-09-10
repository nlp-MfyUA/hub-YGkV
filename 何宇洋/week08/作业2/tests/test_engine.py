import asyncio
import json
import time

import pytest

from research_assistant.config import Settings
from research_assistant.engine import BudgetExceeded, Job, ResearchEngine
from research_assistant.models import DraftReport, Evidence, Extraction, Plan, ResearchRequest, Source, utc_now
from research_assistant.retrieval import TransientRetrievalError
from .fakes import FakeLLM, FakeReader, FakeSearch


def run_job(tmp_path, llm=None, search=None, reader=None, **request):
    engine = ResearchEngine(Settings(api_key="fake", output_dir=tmp_path),
                            llm or FakeLLM(), search or FakeSearch(), reader or FakeReader())
    job = Job(ResearchRequest(topic="测试研究主题", **request))
    asyncio.run(engine.run(job))
    return job


def test_complete_and_artifacts(tmp_path):
    job = run_job(tmp_path)
    assert job.status == "completed"
    assert job.rounds == 1
    assert job.pages_attempted == job.pages_read == 1
    assert job.report["key_conclusions"][0]["confidence"] == "中"
    citation = job.report["key_conclusions"][0]["citations"][0]
    assert citation["url"] == "https://example.com/1"
    assert citation["quote"] == job.evidence[0].quote
    for filename in ["report.json", "report.md", "sources.json", "events.json"]:
        assert (tmp_path / job.id / filename).is_file()
    saved = json.loads((tmp_path / job.id / "report.json").read_text(encoding="utf-8"))
    assert saved == job.report
    assert saved["sources"][0]["published_at"] is None
    assert saved["information_cutoff"]["latest_known_publication_date"] is None
    assert job.events[-1]["kind"] == "stopped"


def test_followup_search(tmp_path):
    search = FakeSearch()
    job = run_job(tmp_path, llm=FakeLLM(sufficient_after=2), search=search)
    assert job.status == "completed"
    assert job.rounds == 2
    assert len(search.calls) == 2
    assert job.pages_attempted == 2


def test_round_limit_partial(tmp_path):
    job = run_job(tmp_path, llm=FakeLLM(sufficient_after=99))
    assert job.status == "partial"
    assert job.rounds == 2
    assert "轮数上限" in job.stop_reason


def test_page_limit_counts_failed_attempts(tmp_path):
    job = run_job(tmp_path, llm=FakeLLM(sufficient_after=99), reader=FakeReader(fail=True), max_pages=1)
    assert job.pages_attempted == 1
    assert job.pages_read == 0
    assert job.status == "failed"
    assert "网页访问上限" in job.stop_reason


def test_search_failure_is_recorded(tmp_path):
    job = run_job(tmp_path, search=FakeSearch(fail=True), llm=FakeLLM(sufficient_after=99))
    assert job.status == "failed"
    assert job.errors
    assert not job.sources
    assert job.report["key_conclusions"][0]["basis"] == "模型推断"


@pytest.mark.parametrize("schema", [Plan, Extraction, DraftReport])
def test_invalid_model_output_falls_back(tmp_path, schema):
    job = run_job(tmp_path, llm=FakeLLM(bad_schema=schema))
    assert job.status in ("failed", "partial")
    assert job.report["partial"]
    assert job.errors


def test_fabricated_quote_rejected(tmp_path):
    job = run_job(tmp_path, llm=FakeLLM(bad_quote=True))
    assert job.sources
    assert not job.evidence
    assert job.status == "failed"
    assert any("摘录不匹配" in e.get("reason", "") for e in job.events)


def test_fabricated_reference_downgraded(tmp_path):
    job = run_job(tmp_path, llm=FakeLLM(bad_reference=True))
    assert job.status == "partial"
    claim = job.report["key_conclusions"][0]
    assert claim["basis"] == "模型推断"
    assert claim["citations"] == []
    assert claim["confidence"] == "低"


def test_expired_budget_skips_external_calls(tmp_path):
    llm = FakeLLM()
    engine = ResearchEngine(Settings(output_dir=tmp_path), llm, FakeSearch(), FakeReader())
    job = Job(ResearchRequest(topic="预算测试", timeout_seconds=10))
    job.started -= 11
    asyncio.run(engine.run(job))
    assert not llm.calls
    assert job.status == "failed"
    assert "预算耗尽" in job.stop_reason


def test_retry_at_most_once(tmp_path):
    async def scenario():
        engine = ResearchEngine(Settings(output_dir=tmp_path), None, None, None)
        job = Job(ResearchRequest(topic="重试测试"))
        attempts = 0
        async def fail():
            nonlocal attempts
            attempts += 1
            raise TransientRetrievalError("临时错误")
        with pytest.raises(TransientRetrievalError):
            await engine.invoke(job, fail, "检索", time.monotonic()+10, 1)
        assert attempts == 2
    asyncio.run(scenario())


def test_deadline_cancels_running_operation(tmp_path):
    async def scenario():
        engine = ResearchEngine(Settings(output_dir=tmp_path), None, None, None)
        job = Job(ResearchRequest(topic="超时测试"))
        cancelled = False
        async def slow():
            nonlocal cancelled
            try:
                await asyncio.sleep(10)
            finally:
                cancelled = True
        started = time.monotonic()
        with pytest.raises(BudgetExceeded):
            await engine.invoke(job, slow, "慢调用", started+0.02, 10)
        assert cancelled
        assert time.monotonic() - started < 1
    asyncio.run(scenario())


def test_shutdown_generates_interrupted_artifact(tmp_path):
    async def scenario():
        engine = ResearchEngine(Settings(output_dir=tmp_path), FakeLLM(delay=10), FakeSearch(), FakeReader())
        job = Job(ResearchRequest(topic="关闭测试"))
        task = asyncio.create_task(engine.run(job))
        await asyncio.sleep(0.01)
        task.cancel()
        await task
        assert job.status == "failed"
        assert "中断" in job.stop_reason
        assert (tmp_path / job.id / "report.json").exists()
    asyncio.run(scenario())


def test_disk_failure_retains_memory_report(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("permission denied")
    monkeypatch.setattr("research_assistant.engine.write_artifacts", fail)
    job = run_job(tmp_path)
    assert job.status == "failed"
    assert job.report is not None
    assert "磁盘失败" in job.stop_reason


def test_expired_generation_budget_preserves_evidence(tmp_path):
    llm = FakeLLM()
    engine = ResearchEngine(Settings(output_dir=tmp_path), llm, FakeSearch(), FakeReader())
    job = Job(ResearchRequest(topic="预算耗尽时保留证据"))
    job.started -= 301
    job.sources.append(Source(id="S1", url="https://example.com/", title="实际来源", publisher="example.com", fetched_at=utc_now()))
    job.evidence.append(Evidence(id="E1", source_id="S1", statement="已经抽取的事实", quote="Verbatim text from the source."))
    asyncio.run(engine.run(job))
    assert not llm.calls
    assert job.status == "partial"
    assert job.report["sections"][0]["claims"][0]["citations"][0]["evidence_id"] == "E1"


def test_transient_page_retry_counts_once(tmp_path):
    class Reader(FakeReader):
        failed_once = False
        async def read(self, url):
            if not self.failed_once:
                self.failed_once = True
                raise TransientRetrievalError("暂时不可用")
            return await super().read(url)
    job = run_job(tmp_path, reader=Reader(), max_pages=1)
    assert job.status == "completed"
    assert job.pages_attempted == 1
    assert len([e for e in job.events if e["kind"] == "retry"]) == 1
