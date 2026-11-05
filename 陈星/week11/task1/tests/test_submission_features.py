"""提交版增加的关联表补全、安全停止与结果对齐测试。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sql_agent.db.catalog import SchemaCatalog
from sql_agent.db.executor import SQLExecutionError, SQLExecutor
from sql_agent.db.validator import SQLValidator
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection
from sql_agent.workflow import SQLAgentWorkflow
import sql_agent.workflow as workflow_module

DB_PATH = Path("ref/chinook.db")


class FakeResponse:
    def __init__(self, value):
        self.final_output = value


def test_auto_complete_join_bridge():
    catalog = SchemaCatalog(DB_PATH)
    assert catalog.complete_join_tables(["customers", "genres"]) == [
        "customers", "genres", "invoice_items", "invoices", "tracks"
    ]
    assert catalog.is_connected(catalog.complete_join_tables(["customers", "genres"]))


def test_bfs_workflow_end_to_end(monkeypatch):
    catalog = SchemaCatalog(DB_PATH)
    wf = SQLAgentWorkflow(
        catalog=catalog,
        validator=SQLValidator(catalog.db_path),
        executor=SQLExecutor(catalog.db_path),
    )
    responses = iter([
        TableSelection(
            tables=["customers", "genres"],
            reason="客户和音乐类型，需要补全 JOIN 路径",
            confidence=0.9,
        ),
        SQLDraft(
            sql=(
                "SELECT DISTINCT c.CustomerId FROM customers c "
                "JOIN invoices i ON c.CustomerId=i.CustomerId "
                "JOIN invoice_items ii ON ii.InvoiceId=i.InvoiceId "
                "JOIN tracks t ON t.TrackId=ii.TrackId "
                "JOIN genres g ON g.GenreId=t.GenreId "
                "WHERE g.Name='Rock'"
            ),
            explanation="查询曾购买 Rock 类型歌曲的客户",
        ),
        FinalAnswer(answer="购买过 Rock 音乐的客户共 59 位。", evidence=["59"]),
    ])

    async def fake_run(agent, prompt, **kwargs):
        return FakeResponse(next(responses))

    monkeypatch.setattr(workflow_module.Runner, "run", fake_run)
    result = asyncio.run(wf.run("购买过 Rock 音乐的客户有多少位？"))
    assert result.error is None, result.error
    assert result.row_count == 59
    assert result.answer == "购买过 Rock 音乐的客户共 59 位。"
    assert result.tables == ["customers", "genres", "invoice_items", "invoices", "tracks"]


def test_unsafe_sql_stops_without_rewrite(monkeypatch):
    catalog = SchemaCatalog(DB_PATH)
    wf = SQLAgentWorkflow(catalog=catalog)
    replies = iter([
        TableSelection(tables=["artists"], reason="名单"),
        SQLDraft(sql="DELETE FROM artists", explanation="unsafe"),
    ])
    calls = []

    async def fake_run(agent, prompt, **kwargs):
        calls.append(agent.name)
        return FakeResponse(next(replies))

    monkeypatch.setattr(workflow_module.Runner, "run", fake_run)
    result = asyncio.run(wf.run("列出所有歌手"))
    assert result.error is not None
    assert result.repair_attempts == 0
    assert result.answer == "SQL 不符合只读安全策略，已拒绝执行。"
    assert len(calls) == 2


def test_validator_and_executor_reject_extension():
    validator = SQLValidator(DB_PATH)
    check = validator.validate("SELECT load_extension('untrusted')")
    assert not check.ok
    assert check.code.value == "unsafe"

    executor = SQLExecutor(DB_PATH)
    with pytest.raises(SQLExecutionError):
        executor.execute("SELECT load_extension('untrusted')")
