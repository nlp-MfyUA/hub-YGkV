#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG 编排：检索 → 组装多模态消息 → 交给 VLM。

「多模态」体现在两处：
  · 资料侧：MinerU 把 PDF 里的图裁出来，并用 VLM 生成了图注。
    图注进 ES 参与检索，真正的图片以 image_url 塞进对话 —— 模型看到的是图，不是图注的文字转述。
  · 提问侧：用户可以一起上传图片。图片和文字在同一条 user message 里，
    content 是 [{"type":"text"}, {"type":"image_url"}, ...] 的数组。
"""

import base64
import io
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
import db
import indexer

log = logging.getLogger("rag")

SYSTEM_PROMPT = (
    "你是一个严谨的多模态文档问答助手，会收到若干条资料编号 S1、S2…，"
    "其中有些是正文，有些是表格，有些是图片（会以图像形式直接给你）。\n"
    "规则：\n"
    "1. 只依据给定资料回答，资料里没有的内容直接说「资料中未提到」，禁止编造。\n"
    "2. 每句结论后面必须标注来源，格式为 [S1]，可连续标注多个，例如 [S1][S3]。\n"
    "3. 资料里若包含图片或表格（如 S3、S7），必须在回答的相关位置用「见图 S8」明确引用它。\n"
    "4. 用简体中文回答，先给结论，再分点说明；可以使用 Markdown 的列表、加粗。\n"
    "5. 不要整段复述资料原文，要归纳；表格只概括关键几行，不要逐行抄。\n"
    "6. 用户提问时可能上传图片（标注为【用户上传图 1】这种），你能直接看到它们。"
    "请先用一两句话概括图片内容，再结合资料作答；不要声称「看不到图片」或「资料未提及图片」。\n"
    "7. 回答控制在 400 字以内。\n"
    "\n"
    "示例：\n"
    "问：表格问答支持哪些问法？\n"
    "答：表格问答主要支持四类问法 [S1]：\n"
    "- **单属性 / 多属性查询**，如「倚天710 芯片是几纳米制程」[S1]；\n"
    "- **约束与排序查询**，如「收益率大于 5% 的理财产品」[S1]；\n"
    "- **聚合计算**，如求平均收益率 [S2]；\n"
    "- **多轮对话与跨表查询** [S2]。\n"
    "相关表结构见图 S3。"
)

_QUESTION_WORDS = re.compile(
    r"请问|请|帮我|帮忙|告诉我|我想知道|什么是|是什么|有哪些|有什么|怎么样|怎么|如何|为什么|"
    r"是否|能否|可以|介绍一下|解释一下|说明一下")
_PUNCT = re.compile(r"[，。？！、；：“”‘’（）()\[\]{}<>《》~\s]+")


# ---------------------------------------------------------------- 图片
def encode_image(path: Path, max_side: int = None) -> Optional[str]:
    """缩放到 max_side 再转 data URL。控制 token 数，也避免请求体过大。"""
    max_side = max_side or config.IMAGE_MAX_SIDE
    try:
        from PIL import Image
        im = Image.open(path)
        im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=86, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:                                  # noqa: BLE001
        log.warning("图片编码失败 %s: %s", path, e)
        return None


# ---------------------------------------------------------------- 检索
def plan_queries(question: str) -> List[str]:
    """原问题 + 去疑问词后的关键词串。短问题单靠 BM25 容易召回偏，双路更稳。"""
    q = (question or "").strip()
    if not q:
        return []
    core = _PUNCT.sub(" ", _QUESTION_WORDS.sub(" ", q)).strip()
    out = [q]
    if core and core != q and len(core) >= 2:
        out.append(core)
    return out


def _row_to_evidence(hit: Dict[str, Any], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = (row.get("text") or hit.get("text") or "").strip()
    img_rel = row.get("image_path")
    if not text and not img_rel:
        return None
    return {
        "chunk_id": hit["chunk_id"],
        "doc_id": hit["doc_id"],
        "filename": hit["filename"],
        "kind": row["kind"],
        "page": row.get("page"),
        "section": row.get("section") or "",
        "text": text[: config.MAX_CHUNK_CHARS],
        "html": (row.get("html") or "")[:4000],
        "image_url": f"/media/{img_rel}" if img_rel else None,
        "score": hit["score"],
    }


def retrieve(question: str, top_k: Optional[int] = None,
             doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    top_k = top_k or config.TOP_K
    hits = indexer.search_multi(plan_queries(question), top_k, doc_ids)
    if not hits:
        return []
    rows = db.chunks_by_ids([h["chunk_id"] for h in hits])
    evidence: List[Dict[str, Any]] = []
    for h in hits:
        row = rows.get(h["chunk_id"])
        if not row:
            continue
        ev = _row_to_evidence(h, row)
        if ev:
            evidence.append(ev)

    # 图文混排的兜底：本次召回全是正文时，补一条最相关的图表块
    if evidence and not any(e["image_url"] for e in evidence):
        pick = indexer.best_visual(question, evidence[0]["doc_id"], doc_ids)
        if pick:
            row = db.chunks_by_ids([pick["chunk_id"]]).get(pick["chunk_id"])
            extra = _row_to_evidence(pick, row) if row else None
            if extra and extra["image_url"]:
                evidence.append(extra)
    return evidence


# ---------------------------------------------------------------- 组装
def _evidence_label(i: int, ev: Dict[str, Any]) -> str:
    where = f"《{ev['filename']}》"
    if ev.get("page") is not None:
        where += f" 第 {int(ev['page']) + 1} 页"
    if ev.get("section"):
        where += f" · {ev['section']}"
    kind = {"image": "图片", "table": "表格"}.get(ev["kind"], "正文")
    return f"[S{i + 1}] {where}（{kind}）"


def build_messages(question: str, evidence: List[Dict[str, Any]],
                   ask_images: Optional[List[Path]] = None
                   ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """返回 (messages, 实际送进模型的图片清单)。

    用户上传的图放在 content 最前面：VLM 对开头出现的图注意力更强，
    而且「第一张图就是用户上传的」这个位置信息本身就能帮模型区分
    「用户给的图」和「资料里的图」，避免它把两者搞混。
    """
    ask_images = ask_images or []
    parts: List[Dict[str, Any]] = []
    used_images: List[Dict[str, Any]] = []

    if ask_images:
        parts.append({"type": "text",
                      "text": f"这次提问，用户上传了 {len(ask_images)} 张图片，"
                              f"就是下面紧跟的这 {len(ask_images)} 张（标注为【用户上传图 N】）。"
                              f"请先看图，再结合后面的资料回答。"})
        for j, p in enumerate(ask_images):
            data_url = encode_image(Path(p))
            if not data_url:
                continue
            parts.append({"type": "text", "text": f"【用户上传图 {j + 1}】"})
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
            used_images.append({"source": f"U{j + 1}", "kind": "user",
                                "url": f"/ask_images/{Path(p).name}",
                                "label": f"用户上传图 {j + 1}"})

    head = ["以下是检索到的资料。\n"]
    for i, ev in enumerate(evidence):
        block = [_evidence_label(i, ev)]
        if ev["kind"] == "image":
            block.append(ev["text"] or "（该图没有可用图注，请直接观察图片内容）")
        else:
            block.append(ev["text"])
        head.append("\n".join(block))
    if not evidence:
        head.append("（本次没有检索到任何相关资料）")

    head.append(f"\n用户问题：{question}")
    if ask_images:
        head.append("（提醒：上面问题里说的「我上传的图」指的是本次对话开头那几张"
                    "【用户上传图】，不是资料里的 S 编号图片。）")
    parts.append({"type": "text", "text": "\n\n".join(head)})

    # 资料里的图片：按证据顺序取前 N 张
    for i, ev in enumerate(evidence):
        if len(used_images) - len(ask_images) >= config.MAX_IMAGES_TO_LLM:
            break
        if ev["kind"] != "image" or not ev.get("image_url"):
            continue
        rel = ev["image_url"].replace("/media/", "", 1)
        path = config.MEDIA_DIR / rel
        if not path.exists():
            continue
        data_url = encode_image(path)
        if not data_url:
            continue
        parts.append({"type": "text", "text": f"【S{i + 1}】对应的图片："})
        parts.append({"type": "image_url", "image_url": {"url": data_url}})
        used_images.append({"source": f"S{i + 1}", "kind": "evidence",
                            "url": ev["image_url"], "label": _evidence_label(i, ev)})

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": parts}]
    return messages, used_images


def public_evidence(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给前端的证据视图：去掉 html 全文，保留展示所需字段。"""
    out = []
    for i, ev in enumerate(evidence):
        out.append({
            "id": f"S{i + 1}",
            "doc_id": ev["doc_id"],
            "filename": ev["filename"],
            "kind": ev["kind"],
            "page": (ev["page"] + 1) if ev.get("page") is not None else None,
            "section": ev["section"],
            "snippet": (ev["text"] or "")[:220],
            "image_url": ev["image_url"],
            "score": ev["score"],
        })
    return out


_CITE = re.compile(r"\[\^?S(\d{1,2})\]|图[片表]?\s*(?:为|是|见|如下)?\s*S(\d{1,2})")


def cited_ids(answer: str, n_evidence: int) -> List[str]:
    """从答案里抽出被引用的证据编号（含「见图 S2」这种不带方括号的写法）。

    0.8B 的模型不一定会严格按格式标注，前端拿到这个列表后可以补一条
    「本次回答基于 S1/S2…」的可点击依据条，避免引用完全丢失。
    """
    seen: List[str] = []
    for m in _CITE.finditer(answer or ""):
        k = m.group(1) or m.group(2)
        tag = f"S{k}"
        if k and 1 <= int(k) <= n_evidence and tag not in seen:
            seen.append(tag)
    return seen
