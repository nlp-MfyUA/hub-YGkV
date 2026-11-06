"""固定示例的离线模型：仍经过真实 LangGraph 图和只读 SQLite 执行。"""

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

EXAMPLES = {
    "列出前 5 位歌手": (["artists"], "SELECT ArtistId, Name FROM artists ORDER BY ArtistId LIMIT 5"),
    "销售额最高的 5 个国家": (["invoices"],
        "SELECT BillingCountry AS Country, ROUND(SUM(Total), 2) AS Revenue "
        "FROM invoices GROUP BY BillingCountry ORDER BY Revenue DESC, Country LIMIT 5"),
    "每种音乐类型有多少首曲目": (["genres", "tracks"],
        "SELECT g.Name AS Genre, COUNT(t.TrackId) AS Tracks FROM genres AS g "
        "LEFT JOIN tracks AS t ON t.GenreId = g.GenreId "
        "GROUP BY g.GenreId, g.Name ORDER BY Tracks DESC, Genre"),
}


class DemoSQLModel(BaseChatModel):
    tables: list[str]
    sql: str

    @property
    def _llm_type(self) -> str:
        return "offline-demo"

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda _: schema(tables=self.tables))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        system = messages[0].content
        if "只根据所提供的 SQL 结果" in system:
            result = json.loads(messages[-1].content)
            count = len(result["rows"])
            answer = f"根据 Chinook 数据，查询返回 {count} 条记录，详细数据见下表。" if count else "没有匹配记录。"
            if result["truncated"]:
                answer += "结果已截断，仅展示前几行。"
        else:
            answer = self.sql
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])


def demo_model(question: str) -> DemoSQLModel:
    if question not in EXAMPLES:
        raise ValueError("离线演示仅支持页面上的三个示例问题；自由提问请使用真实模型模式。")
    tables, sql = EXAMPLES[question]
    return DemoSQLModel(tables=tables, sql=sql)
