# -*- coding: utf-8 -*-
"""报告模块：把研究产物写成 Markdown / HTML / JSON 报告（含来源/过程/置信度）。"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from . import config
from .models import ResearchResult


def _md(result: ResearchResult) -> str:
    lines: list[str] = []
    lines.append(f"# {result.title}\n")
    lines.append(f"**研究主题**：{result.topic}\n")
    if result.summary:
        lines.append(f"**摘要**：{result.summary}\n")
    if result.sections:
        lines.append("## 正文")
        for s in result.sections:
            tag = " *(模型推断：本节无检索来源)*" if s.inferred else ""
            lines.append(f"### {s.heading}{tag}\n{s.body}")
    if result.key_conclusions:
        lines.append("## 关键结论")
        lines.extend(f"- {c}" for c in result.key_conclusions)
    if result.open_questions:
        lines.append("## 遗留问题")
        lines.extend(f"- {q}" for q in result.open_questions)
    if result.sources:
        lines.append("## 来源列表")
        for s in result.sources:
            site = f"（{s.site_name}）" if s.site_name else ""
            lines.append(f"- [{s.title or s.url}]({s.url}) {site}")
    p = result.process
    lines.append("## 研究过程记录")
    lines.append(f"- 检索关键词（{len(p.search_queries)} 个）：{', '.join(p.search_queries) or '无'}")
    lines.append(f"- 已读页面（{len(p.reviewed_urls)} 个）：{', '.join(p.reviewed_urls) or '无'}")
    lines.append(f"- 迭代轮数：{p.iterations}")
    c = result.confidence
    lines.append("## 置信度说明")
    lines.append(f"- 置信度：{c.overall}")
    lines.append(f"- 信息截止：{c.info_cutoff}")
    lines.extend(f"- {n}" for n in c.notes)
    return "\n\n".join(lines)


def _html(result: ResearchResult) -> str:
    """渲染成一份自包含 HTML 报告（样式内联，可直接浏览器打开）。"""
    esc = html.escape
    parts: list[str] = [
        "<!DOCTYPE html>\n<html lang=\"zh\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{esc(result.title)}</title>\n<style>\n"
        "body { font-family: -apple-system,\"PingFang SC\",\"Microsoft YaHei\",sans-serif; "
        "max-width: 900px; margin: 24px auto; padding: 0 16px; color: #222; line-height: 1.7; }\n"
        "h1 { border-bottom: 2px solid #3b82f6; padding-bottom: 8px; }\n"
        "h3 { margin-bottom: 2px; color: #1d4ed8; }\n"
        ".infer { color: #b45309; font-size: 0.85em; font-weight: normal; }\n"
        ".meta { background: #f8fafc; border-left: 4px solid #93c5fd; padding: 10px 14px; border-radius: 4px; }\n"
        "table { border-collapse: collapse; width: 100%; font-size: 0.9em; }\n"
        "th, td { border: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; word-break: break-all; }\n"
        "th { background: #f1f5f9; }\n"
        "code { background: #f1f5f9; padding: 1px 4px; border-radius: 3px; }\n"
        "</style>\n</head>\n<body>\n"
    ]
    parts.append(f"<h1>{esc(result.title)}</h1>")
    parts.append(f"<p><b>研究主题</b>：{esc(result.topic)}</p>")
    if result.summary:
        parts.append(f'<p class="meta"><b>摘要</b>：{esc(result.summary)}</p>')
    if result.sections:
        parts.append("<h2>正文</h2>")
        for s in result.sections:
            infer = ' <span class="infer">（模型推断：本节无检索来源）</span>' if s.inferred else ""
            parts.append(f"<h3>{esc(s.heading)}{infer}</h3>")
            parts.append(f"<p>{esc(s.body).replace(chr(10), '<br>')}</p>")
    if result.key_conclusions:
        parts.append("<h2>关键结论</h2><ul>")
        parts.extend(f"<li>{esc(c)}</li>" for c in result.key_conclusions)
        parts.append("</ul>")
    if result.open_questions:
        parts.append("<h2>遗留问题</h2><ul>")
        parts.extend(f"<li>{esc(q)}</li>" for q in result.open_questions)
        parts.append("</ul>")
    if result.sources:
        parts.append("<h2>来源列表</h2><table><tr><th>#</th><th>标题</th><th>站点</th><th>日期</th></tr>")
        for i, s in enumerate(result.sources, 1):
            title = esc(s.title or s.url)
            site = esc(s.site_name)
            date = esc((s.date or "")[:10])
            parts.append(
                f"<tr><td>{i}</td><td><a href=\"{esc(s.url)}\" target=\"_blank\">{title}</a></td>"
                f"<td>{site}</td><td>{date}</td></tr>"
            )
        parts.append("</table>")
    p = result.process
    parts.append("<h2>研究过程记录</h2>")
    parts.append(f'<p class="meta">迭代轮数：{p.iterations}　|　'
                 f'检索关键词 {len(p.search_queries)} 个：<code>{esc("、".join(p.search_queries) or "无")}</code><br>'
                 f'已读页面 {len(p.reviewed_urls)} 个（详见 JSON）</p>')
    c = result.confidence
    parts.append("<h2>置信度说明</h2>")
    parts.append('<p class="meta">')
    parts.append(f"置信度：<b>{esc(c.overall)}</b>　|　信息截止：{esc(c.info_cutoff)}<br>")
    parts.append("<br>".join(esc(n) for n in c.notes))
    parts.append("</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_html(result: ResearchResult) -> str:
    """返回 HTML 字符串（不落盘）。"""
    return _html(result)


def save(result: ResearchResult) -> str:
    """写 report_<时间戳>.md 与 .json 到 outputs/，返回 md 路径。"""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    md_path = config.OUTPUT_DIR / f"report_{stamp}.md"
    json_path = config.OUTPUT_DIR / f"report_{stamp}.json"
    md_path.write_text(_md(result), encoding="utf-8")
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(md_path)


def save_html(result: ResearchResult, path: str | Path | None = None) -> str:
    """写 HTML 报告：指定 path 写到该处，否则落到 outputs/report_<时间戳>.html。返回路径。"""
    if path is None:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = config.OUTPUT_DIR / f"report_{stamp}.html"
    path = Path(path)
    path.write_text(_html(result), encoding="utf-8")
    return str(path)
