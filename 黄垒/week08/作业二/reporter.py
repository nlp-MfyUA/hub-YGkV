"""成品落盘：把研究结果写成 report/sources/process/confidence 四个 markdown 文件。"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _reg_idmap(sources: list[dict]) -> dict:
    return {s["url"]: s["id"] for s in sources}


def _sanitize_citations(report_md: str, max_id: int) -> str:
    """剔除正文里超出来源范围的 [n] 引用，保证每条引用在 sources.md 里可查。"""
    def _drop(m):
        n = int(m.group(1))
        return "" if n > max_id else m.group(0)
    return re.sub(r"\[(\d{1,4})\]", _drop, report_md)


def write_report(out_dir: Path, report_md: str, max_source_id: int = 0) -> None:
    if not report_md.strip():
        report_md = "（未生成正文）"
    report_md = _sanitize_citations(report_md, max_source_id)
    (out_dir / "report.md").write_text(report_md.lstrip() + "\n", encoding="utf-8")


def write_sources(out_dir: Path, sources: list[dict]) -> None:
    if not sources:
        (out_dir / "sources.md").write_text("（本次研究未引用任何可追溯来源）\n", encoding="utf-8")
        return
    lines = ["# 来源列表", "", "每条结论正文中以 [n] 引用对应编号。", ""]
    for s in sources:
        title = s.get("title") or s.get("url")
        lines.append(f"{s['id']}. **{title}**")
        lines.append(f"   - URL: {s['url']}")
        if s.get("site"):
            lines.append(f"   - 站点: {s['site']}")
        if s.get("date"):
            lines.append(f"   - 发布日期: {s['date']}")
    (out_dir / "sources.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_process(out_dir: Path, topic: str, process: list[dict]) -> None:
    lines = ["# 研究过程记录", ""]
    # 追加本文件生成时间，与 run.log/成品时间线一致
    lines.append(f"> 生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    for rec in process:
        step = rec.get("step", "")
        if step == "start":
            lines.append(f"- 研究主题：{topic}")
            lines.append(f"- 开始时间：{rec.get('start','')}")
        elif step == "plan":
            lines.append(f"- 规划子问题 {rec.get('count', 0)} 个：")
            for q in rec.get("sub_questions", []):
                lines.append(f"    - {q}")
        elif step == "initial_search":
            lines.append(f"### {rec.get('question','')}")
            lines.append(f"首轮检索词（{len(rec.get('queries', []))} 条）:")
            for q in rec.get("queries", []):
                lines.append(f"- `{q}`")
            lines.append(f"- 首轮去重结果：{rec.get('results', 0)} 条（{rec.get('time','')}）")
        elif step.startswith("round_"):
            lines.append(f"- 第 {rec['step'].split('_')[-1]} 轮抽取结论 {rec.get('findings', 0)} 条")
        elif step.startswith("supplement_round_"):
            lines.append(f"- 材料不足 → 补检第{rec['step'].split('_')[-1]}轮（{rec.get('time','')}）：")
            for q in rec.get("queries", []):
                lines.append(f"    - `{q}`")
            if rec.get("new_results") is not None:
                lines.append(f"    - 新增结果：{rec['new_results']} 条")
        elif step == "sub_done":
            lines.append(f"- 该子问题完成：结论 {rec.get('findings',0)} 条，累计材料 {rec.get('materials',0)} 份")
            lines.append("")
    (out_dir / "process.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_confidence(out_dir: Path, all_findings: list[dict], sources: list[dict]) -> None:
    lines = ["# 置信度说明", ""]
    lines.append("## 总体说明")
    lines.append("- 结论的可靠程度分四档：**high**(多源交叉/官方一手信源)、**medium**(单一权威源或媒体)、"
                 "**low**(信源可靠性较弱)、**inference**(模型推断，无来源支撑)。")
    lines.append("- 标为 **inference** 的结论没有可追溯来源，属于模型推断，使用需谨慎。")
    lines.append("- 报告正文 [n] 引用对应 sources.md 中的来源；每条来源均含 URL，可点开复核。")
    lines.append("")

    idmap = _reg_idmap(sources)
    by_sub: dict[str, list] = {}
    for f in all_findings:
        by_sub.setdefault(f.get("sub_question", "其他"), []).append(f)

    lines.append("## 分条结论置信度")
    lines.append("")
    for q, items in by_sub.items():
        lines.append(f"### {q}")
        for i, f in enumerate(items, 1):
            conf = f.get("confidence", "low")
            u = f.get("source_url", "")
            ref = f"[{idmap[u]}]" if u in idmap else "(模型推断)"
            lines.append(f"{i}. （{conf}）{f.get('claim','')} {ref}")
        lines.append("")
    (out_dir / "confidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json_sidecars(out_dir: Path, all_findings: list[dict]) -> None:
    """把结构化 findings 原样存档，便于复查/复用。"""
    (out_dir / "findings.json").write_text(
        json.dumps(all_findings, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outputs(out_dir: Path, topic: str, process: list[dict], all_findings: list[dict],
                  report_md: str, sources: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = sources or []
    max_id = max((s.get("id") or 0) for s in sources) if sources else 0
    write_report(out_dir, report_md, max_source_id=max_id)
    write_sources(out_dir, sources)
    write_process(out_dir, topic, process)
    write_confidence(out_dir, all_findings, sources)
    write_json_sidecars(out_dir, all_findings)
