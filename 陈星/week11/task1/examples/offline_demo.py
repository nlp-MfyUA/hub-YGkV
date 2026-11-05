"""无需 API Key 的离线演示。

说明：Runner.run 被替换为预设输出；演示的是 Workflow 调用、SQLite 执行、
SQL 校验和改写机制，而非真实模型的自然语言理解能力。
运行：python examples/offline_demo.py  (需先 pip install -e .)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sql_agent.db.catalog import SchemaCatalog
from sql_agent.db.executor import SQLExecutor
from sql_agent.db.validator import SQLValidator
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection
from sql_agent.workflow import SQLAgentWorkflow
import sql_agent.workflow as wf_module

DB = Path(__file__).resolve().parents[1] / "ref" / "chinook.db"


class FakeOutput:
    def __init__(self, result):
        self.final_output = result


class OfflineResponses:
    def __init__(self, mode):
        self.mode = mode

    async def run(self, agent, prompt, **kwargs):
        name = agent.name
        if name == "TableSelectAgent":
            if self.mode == "rock":
                return FakeOutput(TableSelection(
                    tables=["customers", "genres"],
                    reason="通过购买明细连接客户与音乐类型",
                    confidence=0.9,
                ))
            if self.mode == "album":
                return FakeOutput(TableSelection(
                    tables=["albums"], reason="统计专辑总数", confidence=0.9
                ))
            return FakeOutput(TableSelection(
                tables=["artists"], reason="歌手名单", confidence=0.9
            ))

        if name == "SQLGeneratorAgent":
            if self.mode == "rock":
                return FakeOutput(SQLDraft(
                    sql=(
                        "SELECT COUNT(DISTINCT c.CustomerId) AS customer_count "
                        "FROM customers c "
                        "JOIN invoices i ON i.CustomerId=c.CustomerId "
                        "JOIN invoice_items ii ON ii.InvoiceId=i.InvoiceId "
                        "JOIN tracks t ON t.TrackId=ii.TrackId "
                        "JOIN genres g ON g.GenreId=t.GenreId "
                        "WHERE g.Name='Rock'"
                    ),
                    explanation="统计购买 Rock 的不重复客户数",
                ))
            if self.mode == "album":
                return FakeOutput(SQLDraft(
                    sql="SELECT COUNT(*) AS album_count FROM albums",
                    explanation="统计专辑总数",
                ))
            return FakeOutput(SQLDraft(
                sql="SELECT ArtistName FROM artists",
                explanation="故意制造不存在的字段，测试自动修复",
            ))

        if name == "SQLRewriteAgent":
            return FakeOutput(SQLDraft(
                sql="SELECT Name FROM artists ORDER BY ArtistId LIMIT 3",
                explanation="使用正确的 Name 字段",
            ))

        if name == "ResultSummaryAgent":
            if self.mode == "rock":
                return FakeOutput(FinalAnswer(
                    answer="购买过 Rock 音乐的客户有 59 位。",
                    evidence=["customer_count=59"],
                ))
            if self.mode == "album":
                return FakeOutput(FinalAnswer(
                    answer="数据库共有 347 张专辑。",
                    evidence=["album_count=347"],
                ))
            return FakeOutput(FinalAnswer(
                answer="前三位歌手：AC/DC、Accept、Aerosmith。",
                evidence=["AC/DC", "Accept", "Aerosmith"],
            ))
        raise AssertionError(f"意外 Agent 名称: {name}")


async def main():
    catalog = SchemaCatalog(DB)
    for mode, question in (
        ("album", "总共有多少张专辑？"),
        ("rock", "购买过 Rock 音乐的客户有多少位？"),
        ("repair", "列出前三位歌手名字"),
    ):
        responses = OfflineResponses(mode)
        # 仅在本地演示进程中替换 Runner；不会发起模型网络请求。
        wf_module.Runner.run = responses.run
        workflow = SQLAgentWorkflow(
            catalog=catalog,
            validator=SQLValidator(catalog.db_path),
            executor=SQLExecutor(catalog.db_path),
        )
        result = await workflow.run(question)
        print("\n" + "=" * 55)
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        assert result.error is None, result.error
    catalog.close()


if __name__ == "__main__":
    asyncio.run(main())
