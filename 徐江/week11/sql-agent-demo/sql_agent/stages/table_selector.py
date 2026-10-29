"""Stage 2 · Table 选择。

职责：根据自然语言问题与全库 schema 的相关性，筛选出候选表，缩小 SQL 生成
阶段的上下文（既提升准确率，也降低 token 消耗）。

策略：优先让 LLM 判断（结构化 JSON 输出）；LLM 不可用或输出非法时，
退化到关键词 / 别名启发式规则；两者都无命中时兜底返回全表。
"""
from __future__ import annotations

import time

from ..db import DatabaseSchema
from ..llm import BaseLLMClient, LLMError
from ..models import STATUS_ERROR, STATUS_OK, STAGE_TABLE_SELECT, LLMUsage, StageTrace
from ..prompts import build_select_tables_messages, extract_json

# 表别名 / 同义词：中文问题 → 英文表名
TABLE_ALIASES: dict[str, list[str]] = {
    "users": ["用户", "客户", "买家", "会员"],
    "orders": ["订单", "下单", "交易"],
    "products": ["商品", "产品", "货物", "品类", "类目"],
    "order_items": ["订单明细", "明细", "销量", "销售", "购买"],
}


class TableSelectionStage:
    name = STAGE_TABLE_SELECT

    def __init__(self, llm: BaseLLMClient):
        self._llm = llm

    def run(self, question: str, schema: DatabaseSchema) -> tuple[list[str], StageTrace]:
        start = time.perf_counter()
        usage = LLMUsage()
        method = "llm"
        reason = ""
        try:
            resp = self._llm.chat(
                build_select_tables_messages(schema.to_prompt(), question),
                task="select_tables",
            )
            usage.prompt_tokens += resp.prompt_tokens
            usage.completion_tokens += resp.completion_tokens
            usage.total_tokens += resp.total_tokens
            usage.calls += 1
            payload = extract_json(resp.content) or {}
            raw_tables = payload.get("tables") or []
            reason = str(payload.get("reason", ""))
            tables = self._sanitize(raw_tables, schema)
            if not tables:
                raise ValueError(f"模型未返回有效表名: {raw_tables!r}")
        except (LLMError, ValueError) as exc:
            method = "heuristic"
            reason = f"LLM 选择失败（{exc}），退化到启发式规则"
            tables = heuristic_select(question, schema)

        duration_ms = (time.perf_counter() - start) * 1000
        trace = StageTrace(
            stage=self.name,
            status=STATUS_OK,
            input_brief=question,
            output_brief=f"选中表: {', '.join(tables)}（方式: {method}）",
            detail=reason,
            duration_ms=duration_ms,
            usage=usage if usage.calls else None,
        )
        return tables, trace

    @staticmethod
    def _sanitize(raw: list, schema: DatabaseSchema) -> list[str]:
        known = {t.lower(): t for t in schema.tables}
        picked: list[str] = []
        for item in raw:
            name = str(item).strip().lower()
            if name in known and known[name] not in picked:
                picked.append(known[name])
        return picked


def heuristic_select(question: str, schema: DatabaseSchema) -> list[str]:
    """关键词 / 别名打分；无命中时返回全部表（兜底，宁全勿缺）。"""
    scores: dict[str, int] = {}
    for table in schema.tables:
        score = 0
        score += 3 * question.lower().count(table.lower())
        for alias in TABLE_ALIASES.get(table, []):
            score += question.count(alias)
        for column in schema.columns_of(table):
            if column in question:
                score += 1
        scores[table] = score
    picked = [t for t, s in scores.items() if s > 0]
    # 订单明细必然挂在订单上，选了明细就把订单一起带上
    if "order_items" in picked and "orders" not in picked:
        picked.append("orders")
    return picked or list(schema.tables)


__all__ = ["TableSelectionStage", "heuristic_select", "STATUS_ERROR"]
