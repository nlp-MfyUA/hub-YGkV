"""评测报告渲染：控制台摘要 + Markdown 报告文件。

Markdown 报告包含：总览指标、逐题明细（问题 / gold SQL / 工作流 SQL /
尝试次数 / 校验与执行错误留痕 / 结果比对 / LLM 总结 / 各 stage 耗时）、
schema 附录。
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

from .runner import (MATCH_EXACT, MATCH_GOLD_ERROR, MATCH_LOOSE, MATCH_MISMATCH,
                     EvalReport, QueryOutcome)

_MATCH_LABEL = {
    MATCH_EXACT: "✅ 一致",
    MATCH_LOOSE: "✅ 一致",
    MATCH_MISMATCH: "❌ 不一致",
    MATCH_GOLD_ERROR: "⚠️ gold 失败",
}


# ------------------------------------------------------------------ 控制台
def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _truncate(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    out = ""
    for ch in text:
        if _display_width(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def render_console(report: EvalReport) -> str:
    m = report.metrics
    lines = [
        "",
        "=" * 72,
        "批量评测汇总",
        "=" * 72,
        f"模型: {report.provider} / {report.model}    重试上限: {report.max_attempts}",
        f"执行成功率: {m.exec_success}/{m.total} ({m.exec_rate:.1%})    "
        f"结果正确率: {m.correct}/{m.total} ({m.correct_rate:.1%}"
        f"，严格 {m.exact_match} / 宽松 {m.loose_match})",
        f"平均尝试次数: {m.avg_attempts:.2f}    平均耗时: {_fmt_ms(m.avg_duration_ms)}    "
        f"总 tokens: {m.total_tokens}",
        f"触发改写重试: {m.retried} 条",
        "-" * 72,
    ]
    header = (f"{_pad('ID', 4)}{_pad('问题', 30)}{_pad('难度', 6)}"
              f"{_pad('尝试', 6)}{_pad('执行', 6)}{_pad('结果', 14)}{_pad('耗时', 9)}tokens")
    lines.append(header)
    lines.append("-" * 72)
    for outcome in report.outcomes:
        r = outcome.result
        exec_mark = "✅" if r.success else "❌"
        result_mark = _MATCH_LABEL[outcome.match].split(" ")[0]
        lines.append(
            f"{_pad(outcome.query.qid, 4)}"
            f"{_pad(_truncate(outcome.query.question, 28), 30)}"
            f"{_pad(outcome.query.difficulty, 6)}"
            f"{_pad(str(r.attempts), 6)}"
            f"{_pad(exec_mark, 6)}"
            f"{_pad(result_mark, 14)}"
            f"{_pad(_fmt_ms(r.total_duration_ms), 9)}"
            f"{r.usage.total_tokens}"
        )
    lines.append("=" * 72)
    if m.stage_error_counts:
        lines.append("各 stage 错误次数: " + "，".join(
            f"{stage}×{count}" for stage, count in m.stage_error_counts.most_common()
        ))
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ Markdown
def render_markdown(report: EvalReport, *, schema_ddl: str = "") -> str:
    m = report.metrics
    lines: list[str] = []
    lines.append("# SQL Agent 工作流批量评测报告")
    lines.append("")
    lines.append(f"- 开始时间：{report.started_at:%Y-%m-%d %H:%M:%S}")
    lines.append(f"- 结束时间：{report.finished_at:%Y-%m-%d %H:%M:%S}")
    lines.append(f"- LLM：`{report.provider}` / `{report.model}`")
    lines.append(f"- 工作流重试上限：{report.max_attempts}")
    lines.append("")
    lines.append("## 一、总览指标")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 测试问题数 | {m.total} |")
    lines.append(f"| 执行成功率 | {m.exec_success}/{m.total}（{m.exec_rate:.1%}） |")
    lines.append(f"| 结果正确率 | {m.correct}/{m.total}（{m.correct_rate:.1%}） |")
    lines.append(f"| ├ 严格一致（列序敏感） | {m.exact_match} |")
    lines.append(f"| └ 宽松一致（忽略列内顺序） | {m.loose_match} |")
    lines.append(f"| 平均尝试次数 | {m.avg_attempts:.2f} |")
    lines.append(f"| 平均单条耗时 | {_fmt_ms(m.avg_duration_ms)} |")
    lines.append(f"| 总 token 用量 | {m.total_tokens} |")
    lines.append(f"| 触发改写重试的问题数 | {m.retried} |")
    if m.stage_error_counts:
        lines.append("| 各 stage 错误次数 | "
                     + "，".join(f"{s}×{c}" for s, c in m.stage_error_counts.most_common())
                     + " |")
    lines.append("")

    lines.append("## 二、逐题明细")
    for outcome in report.outcomes:
        lines.extend(_render_query(outcome))

    lines.append("## 三、结果汇总表")
    lines.append("")
    lines.append("| ID | 难度 | 考察点 | 尝试次数 | 执行 | 结果 | 耗时 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for outcome in report.outcomes:
        r = outcome.result
        lines.append(
            f"| {outcome.query.qid} | {outcome.query.difficulty} "
            f"| {outcome.query.category} | {r.attempts} "
            f"| {'✅' if r.success else '❌'} | {_MATCH_LABEL[outcome.match]} "
            f"| {_fmt_ms(r.total_duration_ms)} |"
        )
    lines.append("")

    if schema_ddl:
        lines.append("## 四、附录：示例数据库 Schema")
        lines.append("")
        lines.append("```sql")
        lines.append(schema_ddl.strip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _render_query(outcome: QueryOutcome) -> list[str]:
    q = outcome.query
    r = outcome.result
    lines = [
        f"### {q.qid} · {q.question}",
        "",
        f"- 难度：{q.difficulty}｜考察点：{q.category}",
        f"- 尝试次数：{r.attempts}｜执行：{'✅ 成功' if r.success else '❌ 失败'}"
        f"｜结果：{_MATCH_LABEL[outcome.match]}（{outcome.match_detail}）",
        f"- 总耗时：{_fmt_ms(r.total_duration_ms)}｜token：{r.usage.total_tokens}",
        "",
        "<details open><summary>工作流最终 SQL</summary>",
        "",
        "```sql",
        r.final_sql or "（未产出）",
        "```",
        "",
        "</details>",
        "",
        "<details><summary>gold SQL（标准答案）</summary>",
        "",
        "```sql",
        q.gold_sql,
        "```",
        "",
        "</details>",
        "",
    ]
    if r.error:
        lines += [f"> ⚠️ 兜底说明：{r.error}", ""]
    if r.summary:
        lines += [f"**LLM 总结**：{r.summary}", ""]

    lines += ["| Stage | 状态 | 尝试 | 耗时 | 说明 |", "| --- | --- | --- | --- | --- |"]
    for trace in r.traces:
        status = {"ok": "✅", "error": "❌", "skipped": "⏭️"}.get(trace.status, trace.status)
        detail = trace.detail or trace.output_brief
        detail = detail.replace("|", "\\|").replace("\n", " ")
        if len(detail) > 120:
            detail = detail[:117] + "..."
        lines.append(
            f"| {trace.stage} | {status} | {trace.attempt or '-'} "
            f"| {_fmt_ms(trace.duration_ms)} | {detail} |"
        )
    lines.append("")
    return lines


def write_markdown_report(report: EvalReport, output_dir: str | Path,
                          *, schema_ddl: str = "") -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.finished_at.strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"eval_report_{stamp}.md"
    path.write_text(render_markdown(report, schema_ddl=schema_ddl), encoding="utf-8")
    return path


__all__ = ["render_console", "render_markdown", "write_markdown_report"]
