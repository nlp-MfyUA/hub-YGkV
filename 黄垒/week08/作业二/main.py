"""深度研究助手 · 综合案例02

用法:
    python main.py "研究主题"                # 全自动跑完并产出 4 类成品
    python main.py "研究主题" --plan-only     # 只打印拆解出的子问题，不执行检索
    python main.py "研究主题" --no-cache      # 忽略磁盘缓存，强制重新检索/抓取
    python main.py "研究主题" --max-subs 4 --max-rounds 2

输出: output/<主题>/ 下生成 report.md / sources.md / process.md / confidence.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import llm
import reader
import reporter
import search

BASE_DIR = Path(__file__).resolve().parent

PLAN_SYSTEM = (
    "你是一个严谨的深度研究规划师。给定研究主题，把它拆解成 4~6 个互不重叠、合起来能覆盖主题的"
    "子问题。对每个子问题，给出用于联网检索的中文关键词和英文关键词（宏观/海外话题务必给英文词，"
    "便于命中 bls.gov、federalreserve.gov、reuters、cnbc 等一手信源）。"
    "重要：这是一个面向『当下』的研究任务，检索词要瞄准【最新一期】数据与【即将召开】的会议——"
    "不要写死在训练数据里已过时的年份，优先使用“最新”“即将”“next/upcoming/latest”这类词，"
    "或使用用户给出的当前日期对应的最新一期。"
    "只输出 JSON，结构：{\"sub_questions\":[{\"question\":\"...\",\"zh_queries\":[\"...\",\"...\"],"
    "\"en_queries\":[\"...\"]}]}"
)

EXTRACT_SYSTEM = (
    "你是一名研究员。给定一个子问题与若干检索材料（材料含标题/URL/摘要，部分含网页全文），"
    "从中提取与该子问题直接相关的关键事实与结论。要求：每个 claim 尽量给出 source_url；"
    "若该 claim 纯属你的推断、材料无法支撑，则 source_url 填 \"\" 且 confidence 填 \"inference\"。"
    "并判断现有材料是否已足够回答该子问题；若不足，给出最多 2 条补充检索 query。"
    "只输出 JSON：{\"findings\":[{\"claim\":\"...\",\"source_url\":\"...\",\"confidence\":\"high|medium|low|inference\"}],"
    "\"sufficient\":true/false,\"reason\":\"...\",\"extra_queries\":[\"...\"]}"
)

SYNTH_SYSTEM = (
    "你是一名金融宏观深度研究员。下面是围绕研究主题搜集到的分条证据（每条证据末尾用 〔来源N〕 "
    "标注它对应的来源编号）。请撰写一份完整的中文研究报告，结构如下（用 markdown 各级标题）：\n"
    "# 摘要\n## 分节正文\n（按主题逻辑分若干小节，每小节用小节标题）\n## 关键结论\n## 遗留问题\n"
    "引用规则（务必严格遵守）：正文凡是来自证据的论断，在句尾用 [n] 标注来源编号，"
    "且 n 必须是下方『来源列表』中真实存在的编号，绝对禁止编造不存在的编号；"
    "证据标注的〔来源N〕只是提示，不代表你可以在正文里引用 N。宁可少引用，也不要引用错误的编号。"
    "若某条证据属于模型推断（无来源），不要给它在正文挂 [n]。"
    "只输出报告 markdown 正文本身，不要额外解释。"
)


def slugify(topic: str) -> str:
    """生成安全的输出目录名（保留中文，替换路径非法字符）。"""
    s = unicodedata.normalize("NFKC", topic).strip()
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", s)
    s = s.strip(" .")[:80]
    return s or "research"


# ---------------------------------------------------------------- plan
def plan_research(topic: str, use_cache: bool = True) -> list[dict]:
    plan_file = BASE_DIR / "output" / slugify(topic) / "plan.json"
    if use_cache and plan_file.exists():
        return json.loads(plan_file.read_text(encoding="utf-8"))
    messages = [
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user",
         "content": f"今天是 {_now()}（当前日期）。研究主题：{topic}。请输出 JSON 规划。"},
    ]
    data = llm.chat_json(messages)
    subs = data.get("sub_questions", []) if isinstance(data, dict) else data
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")
    return subs


def _queries_for(sub: dict) -> list[str]:
    qs = [q.strip() for q in sub.get("zh_queries", []) if q.strip()]
    qs += [q.strip() for q in sub.get("en_queries", []) if q.strip()]
    seen, out = set(), []
    for q in qs:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def _run_searches(queries: list[str], use_cache: bool) -> list[dict]:
    """对一组 query 搜索，按 URL 去重，保留顺序。"""
    seen, results = set(), []
    for q in queries:
        try:
            items = search.search(q, count=6, summary=True, use_cache=use_cache)
        except Exception as e:
            print(f"  [search] 失败 {q!r}: {e}", flush=True)
            continue
        for it in items:
            u = it.get("url", "")
            if not u or u in seen:
                continue
            seen.add(u)
            results.append(it)
    return results


def _build_material(result: dict, use_cache: bool) -> dict:
    """单个检索结果 => 研究材料；尝试抓全文，失败回退摘要。"""
    full = reader.fetch_page(result["url"], use_cache=use_cache) if result.get("url") else None
    body = full or result.get("summary") or result.get("snippet") or ""
    return {
        "title": result.get("title", ""),
        "url": result.get("url", ""),
        "siteName": result.get("siteName", ""),
        "datePublished": result.get("datePublished", ""),
        "fetched": bool(full),
        "body": body,
    }


def _materials_block(materials: list[dict], limit_chars: int = 60000) -> str:
    lines, total = [], 0
    for i, m in enumerate(materials, 1):
        src = m.get("fetched") and "网页全文" or "搜索引擎摘要"
        date = m.get("datePublished") or "未知日期"
        head = f"【材料{i}】{m['title']} | {m['siteName']} | {date} | {src}\nURL: {m['url']}\n"
        seg = head + (m.get("body") or "")[:8000] + "\n\n"
        if total + len(seg) > limit_chars and lines:
            break
        lines.append(seg)
        total += len(seg)
    return "".join(lines)


def research_subquestion(sub: dict, use_cache: bool, max_rounds: int, process: list[dict],
                         url_meta: dict[str, dict]) -> list[dict]:
    """研究单个子问题，返回 findings；同时把过程与来源元信息写入外部容器。"""
    question = sub["question"]
    print(f"\n▶ 子问题: {question}", flush=True)
    queries = _queries_for(sub)
    materials: list[dict] = []
    seen_url = set()

    def remember_meta(r: dict) -> None:
        """记录 URL -> {site,date,title}，供 sources.md 与报告引用用。"""
        u = r.get("url", "")
        if u:
            url_meta.setdefault(u, {"site": r.get("siteName", ""), "date": r.get("datePublished", ""),
                                    "title": r.get("title", "")})

    def add_results(results: list[dict]) -> None:
        for r in results:
            if r["url"] not in seen_url:
                seen_url.add(r["url"])
                remember_meta(r)
                materials.append(_build_material(r, use_cache))

    add_results(_run_searches(queries, use_cache))
    process.append({"step": "initial_search", "question": question, "queries": queries,
                    "results": len(materials), "time": _now()})
    print(f"  首轮检索命中 {len(materials)} 条去重结果", flush=True)

    all_findings: list[dict] = []
    for rnd in range(1, max_rounds + 1):
        block = _materials_block(materials)
        messages = [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user",
             "content": f"子问题：{question}\n\n检索材料：\n{block}\n\n请输出 JSON（含 findings/sufficient/extra_queries）。"},
        ]
        data = llm.chat_json(messages, max_tokens=3000)
        findings = data.get("findings", []) if isinstance(data, dict) else []
        for f in findings:
            f.setdefault("sub_question", question)
            all_findings.append(f)
        sufficient = bool(data.get("sufficient", True)) if isinstance(data, dict) else True
        print(f"  第 {rnd} 轮抽取 {len(findings)} 条结论, sufficient={sufficient}", flush=True)

        if sufficient or rnd == max_rounds or not (isinstance(data, dict) and data.get("extra_queries")):
            break

        extra = [q for q in (data.get("extra_queries") or []) if q.strip()][:2]
        print(f"  材料不足，补检: {extra}", flush=True)
        n_before = len(materials)
        add_results(_run_searches(extra, use_cache))
        new_read = len(materials) - n_before
        process.append({"step": f"supplement_round_{rnd}", "question": question,
                        "queries": extra, "new_results": new_read, "time": _now()})
        if new_read == 0:
            break

    process.append({"step": "sub_done", "question": question,
                    "findings": len(all_findings), "materials": len(materials), "time": _now()})
    return all_findings


# ---------------------------------------------------------------- synthesize
def build_source_registry(all_findings: list[dict], url_meta: dict[str, dict]) -> tuple[list[dict], dict]:
    """为每个 source_url 分配稳定编号，返回 ([{id,url,title,site,date}], url->id)。"""
    reg, idmap = [], {}
    for f in all_findings:
        u = (f.get("source_url") or "").strip()
        if not u or u in idmap:
            continue
        meta = url_meta.get(u, {})
        idmap[u] = len(reg) + 1
        reg.append({"id": idmap[u], "url": u,
                    "title": meta.get("title") or f.get("source_title") or u,
                    "site": meta.get("site", ""), "date": meta.get("date", "")})
    return reg, idmap


def synthesize_report(topic: str, all_findings: list[dict], sources: list[dict],
                      idmap: dict) -> str:
    src_lines = [f"[{s['id']}] {s['title']} — {s['url']}" for s in sources]
    src_index = "\n".join(src_lines) if src_lines else "(无外部来源)"

    evidence_lines = []
    for i, f in enumerate(all_findings, 1):
        u = (f.get("source_url") or "").strip()
        tag = f"〔来源{idmap[u]}〕" if u in idmap else "〔无来源·模型推断〕"
        conf = f.get("confidence", "")
        evidence_lines.append(f"证据{i}（confidence={conf}）{f.get('claim','')} {tag}")
    evidence = "\n".join(evidence_lines)

    messages = [
        {"role": "system", "content": SYNTH_SYSTEM},
        {"role": "user",
         "content": (
             f"研究主题：{topic}\n"
             f"信息检索截止时间：{_now()}\n\n"
             f"--- 来源列表(正文请用其编号 [n] 引用) ---\n{src_index}\n\n"
             f"--- 分条证据 ---\n{evidence}\n\n"
             f"请撰写研究报告 markdown。"
         )},
    ]
    return llm.chat(messages, temperature=0.4, max_tokens=6000)


# ---------------------------------------------------------------- cli
def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="深度研究助手")
    parser.add_argument("topic", nargs="?", default="大非农数据及即将到来的议息会议的影响与挑战",
                        help="研究主题")
    parser.add_argument("--plan-only", action="store_true", help="只拆解子问题，不执行检索")
    parser.add_argument("--no-cache", action="store_true", help="禁用磁盘缓存")
    parser.add_argument("--max-subs", type=int, default=None, help="最多研究的子问题数")
    parser.add_argument("--max-rounds", type=int, default=2, help="每子问题最大检索轮次")
    parser.add_argument("--synth-only", action="store_true",
                        help="跳过检索，用缓存的研究证据重新综合成稿")
    args = parser.parse_args()

    use_cache = not args.no_cache
    topic = args.topic.strip()
    out_dir = BASE_DIR / "output" / slugify(topic)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"研究主题: {topic}", flush=True)
    print(f"输出目录: {out_dir}", flush=True)
    process: list[dict] = [{"start": _now(), "topic": topic}]

    print("\n【1/3】规划子问题 ...", flush=True)
    subs = plan_research(topic, use_cache=use_cache)
    for i, s in enumerate(subs, 1):
        q = s.get("question", "")
        nq = len(_queries_for(s))
        print(f"  S{i}: {q}  ({nq} 条检索词)", flush=True)
    if args.max_subs:
        subs = subs[: args.max_subs]
    process.append({"step": "plan", "count": len(subs), "sub_questions": [s["question"] for s in subs]})

    if args.plan_only:
        print("\n--plan-only 已打印规划，未执行检索。", flush=True)
        reporter.write_outputs(out_dir, topic, process, all_findings=[], report_md="", sources=[])
        print("规划已写入 plan.json / process.md。", flush=True)
        return 0

    if args.synth_only:
        print("\n--synth-only：复用缓存证据，仅重新综合成稿 ...", flush=True)
        all_findings = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
        url_meta = json.loads((out_dir / "url_meta.json").read_text(encoding="utf-8"))
        # 过程记录优先复用研究阶段持久化的版本，避免被覆盖成只有规划
        if (out_dir / "process.json").exists():
            process = json.loads((out_dir / "process.json").read_text(encoding="utf-8"))
        sources, idmap = build_source_registry(all_findings, url_meta)
        report_md = synthesize_report(topic, all_findings, sources, idmap)
        reporter.write_outputs(out_dir, topic, process, all_findings, report_md, sources=sources)
        print(f"完成。成品位于:\n  {out_dir}", flush=True)
        return 0

    # 【2/3】逐个研究子问题
    print("\n【2/3】逐子问题检索研究 ...", flush=True)
    url_meta: dict[str, dict] = {}
    all_findings: list[dict] = []
    for sub in subs:
        all_findings.extend(research_subquestion(sub, use_cache, args.max_rounds, process, url_meta))
    print(f"\n共抽取 {len(all_findings)} 条证据", flush=True)
    (out_dir / "url_meta.json").write_text(
        json.dumps(url_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "process.json").write_text(
        json.dumps(process, ensure_ascii=False, indent=2), encoding="utf-8")

    sources, idmap = build_source_registry(all_findings, url_meta)

    # 【3/3】综合成稿
    print("\n【3/3】综合成稿 ...", flush=True)
    report_md = synthesize_report(topic, all_findings, sources, idmap)

    reporter.write_outputs(out_dir, topic, process, all_findings, report_md, sources=sources)
    print(f"\n完成。成品位于:\n  {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n[出错] {e}", flush=True)
        sys.exit(1)
