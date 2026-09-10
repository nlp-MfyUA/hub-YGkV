"""研究 pipeline：固定五类调用（规划/检索/抽取/判断/综合），events 全程落库并实时通知订阅者。

流程：规划 → [检索 → 抽取 → 判断补检] × max_rounds → 综合。
轮次是任务级配置，全模块共用；达到上限后不再调用任何模块，直接进综合，
并在报告"遗留问题"中显式说明。
"""
import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import bocha
import db
import llm

ACTIVE_TASKS: dict[int, threading.Thread] = {}
# 每个任务一组 SSE 订阅者；emit 时除落库外，把事件推给这些队列
SUBSCRIBERS: dict[int, list[queue.Queue]] = {}


class TaskContext:
    def __init__(self, task_id: int, model: dict, topic: str, max_rounds: int):
        self.task_id = task_id
        self.model = model
        self.topic = topic
        self.max_rounds = max_rounds
        self.seq = 0
        self.all_facts: list[dict] = []
        self.all_gaps: list[str] = []
        self.source_map: dict[str, dict] = {}  # url -> {title, url}
        self.search_cutoff = datetime.now().strftime("%Y-%m-%d %H:%M")

    def emit(self, etype: str, payload: dict):
        self.seq += 1
        row = {
            "seq": self.seq,
            "type": etype,
            "payload": json.dumps(payload, ensure_ascii=False),
        }
        db.execute(
            "INSERT INTO events (task_id, seq, type, payload) VALUES (?, ?, ?, ?)",
            (self.task_id, row["seq"], row["type"], row["payload"]),
        )
        for q in SUBSCRIBERS.get(self.task_id, []):
            q.put(row)

    def notify_done(self, status: str):
        for q in SUBSCRIBERS.get(self.task_id, []):
            q.put(None)  # 哨兵：任务已终态，订阅方结束流

    def register_source(self, title: str, url: str):
        if url and url not in self.source_map:
            self.source_map[url] = {"title": title, "url": url}


def start(task_id: int):
    t = threading.Thread(target=run_research, args=(task_id,), daemon=True)
    ACTIVE_TASKS[task_id] = t
    t.start()


def run_research(task_id: int):
    task = db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not task:
        return
    model = db.query_one(
        "SELECT * FROM models WHERE id = ? AND user_id = ?",
        (task["model_id"], task["user_id"]),
    )
    if not model:
        _fail(task_id, "所选模型不存在")
        return

    ctx = TaskContext(task_id, model, task["topic"], task["max_rounds"])

    db.execute("UPDATE tasks SET status='running', updated_at=datetime('now','localtime') WHERE id=?", (task_id,))
    ctx.emit("task.started", {"topic": task["topic"], "max_rounds": task["max_rounds"]})

    try:
        # 运行前探活一次，失败直接 error 终止
        if not llm.health_check(model, model["id"]):
            _fail(task_id, "模型连接失败，请检查 base_url / api_key / model_name")
            return

        _run(ctx)
        db.execute(
            "UPDATE tasks SET status='done', updated_at=datetime('now','localtime') WHERE id=?",
            (task_id,),
        )
        ctx.emit("report.done", {"task_id": task_id})
        ctx.notify_done("done")
    except Exception as e:  # noqa: BLE001
        _fail(task_id, str(e))
    finally:
        ACTIVE_TASKS.pop(task_id, None)


def _fail(task_id: int, message: str):
    db.execute(
        "UPDATE tasks SET status='error', error=?, updated_at=datetime('now','localtime') WHERE id=?",
        (message, task_id),
    )
    seq = db.query_one("SELECT COALESCE(MAX(seq),0) AS s FROM events WHERE task_id=?", (task_id,))["s"] + 1
    db.execute(
        "INSERT INTO events (task_id, seq, type, payload) VALUES (?, ?, 'task.error', ?)",
        (task_id, seq, json.dumps({"message": message}, ensure_ascii=False)),
    )
    ctx_notify = None  # 落库后广播
    for q in SUBSCRIBERS.get(task_id, []):
        q.put({"seq": seq, "type": "task.error", "payload": json.dumps({"message": message}, ensure_ascii=False)})
        q.put(None)


def _run(ctx: TaskContext):
    # 1) 规划
    ctx.emit("planning.started", {})
    plan = llm.chat_json(
        ctx.model,
        system="你是一名研究规划助手。把研究主题拆分为子问题，帮助后续检索覆盖不同侧面。",
        user=(
            f"研究主题：{ctx.topic}\n"
            '请拆分为 3~5 个子问题，覆盖不同侧面（现状、数据、争议、趋势等）。输出 JSON：{"subquestions": ["...", ...]}'
        ),
    )
    subquestions = [str(q) for q in plan.get("subquestions", [])][:5]
    if not subquestions:
        raise RuntimeError("规划失败：未得到子问题")
    ctx.emit("planning.done", {"subquestions": subquestions})

    followup_queries: list[str] = subquestions
    judged_sufficient = False

    for rnd in range(1, ctx.max_rounds + 1):
        ctx.emit("round.started", {"round": rnd, "max_rounds": ctx.max_rounds})

        # 2) 检索（代码调 Bocha，不走 LLM）
        pages: list[dict] = []
        seen_urls: set[str] = set()
        for q in followup_queries:
            results = bocha.web_search(q, count=5)
            fresh = [r for r in results if r["url"] and r["url"] not in seen_urls]
            seen_urls.update(r["url"] for r in fresh)
            pages.extend(fresh)
            ctx.emit("searched", {"round": rnd, "query": q, "result_count": len(results), "new_pages": len(fresh)})
        ctx.emit("searched.summary", {"round": rnd, "total_pages": len(pages)})

        if not pages:
            ctx.emit("page.skipped", {"round": rnd, "reason": "未检索到可用结果"})

        # 3) 抽取：逐页并行，一页一调用
        extracted = _extract_pages(ctx, pages)
        fact_count = sum(len(p.get("facts", [])) for p in extracted)
        ctx.emit("extracted.summary", {"round": rnd, "page_count": len(pages), "fact_count": fact_count})

        # 4) 判断补检（输入规模截断，避免 prompt 过长）
        ctx.emit("judge.started", {"round": rnd})
        verdict = llm.chat_json(
            ctx.model,
            system="你是一名研究充分性评审。基于已抽取的事实与缺口，判断是否需要补充检索。",
            user=(
                f"研究主题：{ctx.topic}\n\n"
                f"已抽取事实（JSON 数组，最多列前 150 条）：\n{json.dumps(ctx.all_facts[:150], ensure_ascii=False)}\n\n"
                f"各页报告的缺口（JSON 数组，最多列前 40 条）：\n{json.dumps(ctx.all_gaps[:40], ensure_ascii=False)}\n\n"
                f"信息是否足以支撑报告？若不足，给出下一轮要补充检索的关键词（最多 {len(followup_queries)} 个）。"
                '输出 JSON：{"sufficient": true/false, "reason": "...", "followup_queries": ["...", ...]}'
            ),
        )
        sufficient = bool(verdict.get("sufficient", False))
        followups = [str(x) for x in verdict.get("followup_queries", [])] if not sufficient else []
        ctx.emit("judge.done", {
            "round": rnd,
            "sufficient": sufficient,
            "reason": verdict.get("reason", ""),
            "followup_queries": followups,
        })

        if sufficient:
            judged_sufficient = True
            break
        followup_queries = followups or followup_queries

    # 5) 综合报告
    ctx.emit("synthesis.started", {"judged_sufficient": judged_sufficient})
    source_list = list(ctx.source_map.values())
    url_to_no = {u["url"]: i for i, u in enumerate(source_list, 1)}
    facts_cited = []
    for f in ctx.all_facts:
        no = url_to_no.get(f.get("source_url", ""))
        facts_cited.append({
            "fact": f.get("statement", ""),
            "quote": f.get("quote", ""),
            "source": no or 0,
            "source_url": f.get("source_url", ""),
        })

    # 控制综合输入规模：事实按来源去重后截断，避免一次塞几百条导致超时/截断
    facts_cited = facts_cited[:200]
    gaps_cap = ctx.all_gaps[:60]
    gaps_note = "" if len(ctx.all_gaps) == len(gaps_cap) else f"（仅列出前 {len(gaps_cap)} 条，共 {len(ctx.all_gaps)} 条）"

    report_md = llm.chat_text(
        ctx.model,
        system=(
            "你是一名研究报告撰写助手。基于给定的带编号来源撰写 Markdown 报告。"
            "规则：\n"
            "1. 结论引用来源用 [n] 标注，n 是来源编号；无来源支撑的结论必须标注「模型推断」。\n"
            "2. 置信度：≥2 个独立来源支撑的结论为高，单来源为中，无来源为低（模型推断）。"
            "「关键结论」章节每条结论后面注明置信度（高/中/低）。\n"
            "3. 报告结构必须完整包含：# 标题 / ## 摘要 / 正文分节 / ## 关键结论 / ## 遗留问题 / ## 来源列表（编号+标题+URL）。\n"
            "4. 即使没有明显缺口，也要写「## 遗留问题」章节，说明信息边界与截止时间限制。\n"
            "5. 只输出 Markdown 正文，内容要完整，不要中途截断。"
        ),
        user=(
            f"研究主题：{ctx.topic}\n"
            f"信息截止时间：{ctx.search_cutoff}（报告头部必须注明）\n"
            f"最大轮次：{ctx.max_rounds}\n"
            f"是否检索充分：{'是' if judged_sufficient else '否（已达轮次上限）'}\n\n"
            f"来源列表：\n{json.dumps(source_list, ensure_ascii=False)}\n\n"
            f"已抽取事实（source 字段为来源编号，0 表示无来源）：\n{json.dumps(facts_cited, ensure_ascii=False)}\n\n"
            f"已知缺口{gaps_note}：\n{json.dumps(gaps_cap, ensure_ascii=False)}\n"
            + (
                f"\n注意：已达到最大轮次 {ctx.max_rounds}，未继续补检，请在「遗留问题」章节显式说明，并列出上述缺口。"
                if not judged_sufficient else ""
            )
        ),
        temperature=0.3,
        max_tokens=8000,
    )

    meta = {
        "model_name": ctx.model["model_name"],
        "model_id": ctx.model["id"],
        "max_rounds": ctx.max_rounds,
        "judged_sufficient": judged_sufficient,
        "search_cutoff": ctx.search_cutoff,
        "fact_count": len(ctx.all_facts),
        "source_count": len(source_list),
    }
    db.execute(
        "INSERT INTO reports (task_id, report_md, sources, meta) VALUES (?, ?, ?, ?)",
        (
            ctx.task_id,
            report_md,
            json.dumps(source_list, ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False),
        ),
    )
    ctx.emit("report.generated", {
        "sources": source_list,
        "meta": meta,
    })


def _extract_pages(ctx: TaskContext, pages: list[dict]) -> list[dict]:
    """逐页并行抽取，一页一调用。抽取输入 = Bocha 摘要 + URL，不抓网页正文。"""
    results: list[dict] = []

    def one(page: dict) -> dict:
        ctx.register_source(page.get("title", ""), page.get("url", ""))
        out = {
            "url": page["url"],
            "title": page.get("title", ""),
            "relevance": 0,
            "facts": [],
            "gaps": [],
        }
        try:
            res = llm.chat_json(
                ctx.model,
                system="你是一名信息抽取助手。从给定的网页摘要中抽取与研究主题相关的事实。",
                user=(
                    f"研究主题：{ctx.topic}\n"
                    f"网页标题：{page.get('title','')}\n"
                    f"网页 URL：{page['url']}\n"
                    f"网页摘要：{page.get('summary','')}\n\n"
                    "请抽取事实。每条 fact 的 source_url 必须是该网页 URL，quote 是摘要中的原句。"
                    '输出 JSON：{"relevance": 0~1, "facts": [{"statement": "...", "quote": "...", "source_url": "..."}], "gaps": ["..."]}'
                ),
            )
            out["relevance"] = res.get("relevance", 0)
            out["facts"] = [f for f in res.get("facts", []) if isinstance(f, dict) and f.get("statement")]
            out["gaps"] = [str(g) for g in res.get("gaps", [])]
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)
            out["gaps"].append(f"该页抽取失败：{e}")
        for f in out["facts"]:
            ctx.all_facts.append({
                "statement": f.get("statement", ""),
                "quote": f.get("quote", ""),
                "source_url": f.get("source_url") or page["url"],
            })
        ctx.all_gaps.extend(out["gaps"])
        ctx.emit("page.extracted", {
            "url": page["url"],
            "title": page.get("title", ""),
            "relevance": out["relevance"],
            "fact_count": len(out["facts"]),
            "gaps": out["gaps"],
            "error": out.get("error"),
        })
        return out

    if pages:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(one, pages))
    return results
