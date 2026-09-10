import json
import re
from pathlib import Path

from .models import DraftClaim, DraftReport, DraftSection, Evidence, Source, utc_now


def clean_text(text: str) -> str:
    # 来源链接统一由程序生成，不接受模型在正文中编造 URL。
    return re.sub(r"https?://\S+", "（未核验链接已省略）", text)


def build_report(topic: str, draft: DraftReport, sources: list[Source], evidence: list[Evidence],
                 partial: bool, reason: str, usage: dict) -> dict:
    source_map = {s.id: s for s in sources}
    evidence_map = {e.id: e for e in evidence if e.source_id in source_map}
    invalid_references = []

    def convert(claim: DraftClaim) -> dict:
        ids = list(dict.fromkeys(claim.evidence_ids))
        missing = [ref for ref in ids if ref not in evidence_map]
        invalid_references.extend(missing)
        # 混有不存在引用时整条降为推断，避免留下看似支持整条结论的局部引用。
        refs = [] if missing else [evidence_map[ref] for ref in ids]
        citations = [{
            "evidence_id": e.id, "source_id": e.source_id,
            "url": source_map[e.source_id].url, "title": source_map[e.source_id].title,
            "publisher": source_map[e.source_id].publisher, "quote": e.quote,
        } for e in refs]
        level, explanation = claim.confidence, clean_text(claim.confidence_reason)
        if not refs:
            level, explanation = "低", "无可核验来源，属于模型推断。" + explanation
        elif level == "高" and len({c["publisher"] for c in citations}) < 2:
            level, explanation = "中", "尚缺不同来源交叉核验。" + explanation
        if draft.conflicts and level == "高":
            level, explanation = "中", "本报告存在来源冲突，需人工核验。" + explanation
        return {"text": clean_text(claim.text), "basis": "来源证据" if refs else "模型推断",
                "citations": citations, "confidence": level, "confidence_reason": explanation}

    report = {
        "topic": topic, "generated_at": utc_now(), "partial": partial,
        "stop_reason": reason,
        "summary": [convert(c) for c in draft.summary],
        "sections": [{"title": clean_text(s.title), "claims": [convert(c) for c in s.claims]}
                     for s in draft.sections],
        "key_conclusions": [convert(c) for c in draft.key_conclusions],
        "unresolved_questions": [clean_text(q) for q in draft.unresolved_questions],
        "conflicts": [clean_text(c) for c in draft.conflicts],
        "sources": [s.model_dump() for s in sources],
        "evidence": [e.model_dump() for e in evidence],
        "usage": usage,
        "information_cutoff": {
            "retrieval_completed_at": utc_now(),
            "latest_known_publication_date": max((s.published_at for s in sources if s.published_at), default=None),
            "note": "仅覆盖本次实际读取页面；抓取时间不是发布日期，也不保证信息截至抓取时仍有效。页面发布日期由元数据抽取，可能未知或不准确。",
        },
        "confidence_note": "高/中/低是基于证据覆盖、来源和冲突情况的定性判断，不是统计概率；引用存在和摘录匹配不等于结论已获独立事实核查。",
        "warnings": [],
    }
    if invalid_references:
        report["partial"] = True
        report["warnings"].append("部分模型引用不存在，对应结论已降为模型推断。")
    return report


def fallback_draft(evidence: list[Evidence], questions: list[str], reason: str) -> DraftReport:
    claims = [DraftClaim(text=e.statement, evidence_ids=[e.id], confidence="低",
                         confidence_reason="仅完成证据抽取，尚未完成综合核验。") for e in evidence[:8]]
    if not claims:
        claims = [DraftClaim(text="未获得可核验的网页证据，无法形成可靠研究结论。",
                             confidence_reason="没有可用证据。")]
    return DraftReport(
        summary=claims[:1], sections=[DraftSection(title="已收集证据", claims=claims)],
        key_conclusions=claims[:3], unresolved_questions=list(dict.fromkeys([reason, *questions]))[:15],
    )


def markdown_text(value: str) -> str:
    value = value.replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", value)


def render_markdown(report: dict) -> str:
    lines = [f"# {markdown_text(report['topic'])}", "", f"生成时间：{report['generated_at']}", "",
             f"报告状态：{'部分完成' if report['partial'] else '完成'}", "",
             f"停止原因：{markdown_text(report['stop_reason'])}", ""]

    def claims(items):
        for claim in items:
            refs = " ".join(f"[{c['source_id']}]" for c in claim["citations"])
            lines.extend([f"- {markdown_text(claim['text'])} {refs}",
                          f"  依据：{claim['basis']}；置信度：{claim['confidence']}。{markdown_text(claim['confidence_reason'])}", ""])
            for citation in claim["citations"]:
                lines.extend([f"  证据 {citation['evidence_id']}：{markdown_text(citation['quote'])}", ""])

    lines.extend(["## 摘要", ""])
    claims(report["summary"])
    for section in report["sections"]:
        lines.extend([f"## {markdown_text(section['title'])}", ""])
        claims(section["claims"])
    lines.extend(["## 关键结论", ""])
    claims(report["key_conclusions"])
    for title, field in [("遗留问题", "unresolved_questions"), ("来源冲突", "conflicts"), ("限制与警告", "warnings")]:
        lines.extend([f"## {title}", ""])
        lines.extend(f"- {markdown_text(q)}" for q in report[field])
        if not report[field]:
            lines.append("未发现；不代表已排除所有遗漏。")
        lines.append("")
    lines.extend(["## 来源列表", ""])
    for source in report["sources"]:
        url = source['url'].replace('<', '%3C').replace('>', '%3E')
        lines.extend([f"- [{source['id']}] [{markdown_text(source['title'])}](<{url}>)",
                      f"  来源：{markdown_text(source['publisher'])}；发布日期：{source['published_at'] or '未知'}；抓取时间：{source['fetched_at']}", ""])
    lines.extend(["## 信息截止与置信度说明", "", report["information_cutoff"]["note"], "",
                  f"抓取完成时间：{report['information_cutoff']['retrieval_completed_at']}", "",
                  f"已知最晚发布日期：{report['information_cutoff']['latest_known_publication_date'] or '未知'}", "",
                  report["confidence_note"], "", "## 模型用量", "", json.dumps(report["usage"], ensure_ascii=False), ""])
    return "\n".join(lines)


def write_artifacts(directory: Path, report: dict, events: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    files = {"report.json": json.dumps(report, ensure_ascii=False, indent=2),
             "report.md": render_markdown(report),
             "sources.json": json.dumps(report["sources"], ensure_ascii=False, indent=2),
             "events.json": json.dumps(events, ensure_ascii=False, indent=2)}
    for name, content in files.items():
        temp = directory / (name + ".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(directory / name)
