#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""切块：把 MinerU 的块流变成可检索的 chunk。

三条规则：
  1. 连续正文合并到 ~MAX_CHUNK_CHARS，超了就断；跨页也断（读者定位更准）。
  2. 图片 / 表格各自成块——它们是「多模态证据」，必须能单独被引用和图注召回。
  3. 维护标题栈，给每个 chunk 打上 `章节路径`，检索时命中标题能显著提分，
     回答里也能告诉用户「这段话出自 3.2 节」。
"""

import re
from typing import Any, Dict, List

import config

_WS = re.compile(r"[ \t\u3000]+")


def _clean(s: str) -> str:
    return _WS.sub(" ", (s or "")).strip()


class _Section:
    """维护标题层级，输出「一级 › 二级 › 三级」。"""

    def __init__(self) -> None:
        self.stack: List[str] = []

    def push(self, level: int, title: str) -> None:
        title = _clean(title)
        if not title:
            return
        level = max(1, min(level, 6))
        self.stack = self.stack[:level - 1]
        while len(self.stack) < level - 1:
            self.stack.append("")
        self.stack.append(title[:120])

    @property
    def path(self) -> str:
        return " › ".join(x for x in self.stack if x)


def build_chunks(doc_id: str, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    section = _Section()
    buf: List[str] = []
    buf_meta: Dict[str, Any] = {"page": None, "bbox": None, "section": ""}

    def flush() -> None:
        nonlocal buf, buf_meta
        text = _clean("\n".join(buf))
        buf = []
        if not text:
            return
        chunks.append({
            "id": f"{doc_id}-c{len(chunks):04d}",
            "idx": len(chunks),
            "kind": "text",
            "section": buf_meta["section"],
            "text": text,
            "html": None,
            "image_path": None,
            "page": buf_meta["page"],
            "bbox": _fmt_bbox(buf_meta["bbox"]),
        })
        buf_meta = {"page": None, "bbox": None, "section": section.path}

    for b in blocks:
        btype = b.get("type")
        if btype == "text" and (b.get("level") or 0) > 0 and (b.get("text") or "").strip():
            # 标题：先收尾上一块，再更新章节路径，标题本身也留在下一块的开头
            flush()
            section.push(int(b["level"]), b["text"])
            buf_meta["section"] = section.path
            buf_meta["page"] = b.get("page")
            continue

        if btype == "image":
            flush()
            caption = _clean(" ".join(x for x in [b.get("caption") or "", b.get("text") or ""] if x))
            if not caption:
                # MinerU 没能给这张图生成图注（纯装饰图或识别失败）。
                # 不给个兜底文本它就永远检索不到；用章节名兜底，问题问到该章节时
                # 这张图有机会作为证据出现，prompt 里会注明「无图注，请直接看图」。
                caption = f"{section.path or '文档'} 中的插图"
            chunks.append({
                "id": f"{doc_id}-c{len(chunks):04d}",
                "idx": len(chunks),
                "kind": "image",
                "section": section.path,
                "text": caption,                 # MinerU 高级档的 VLM 图注，是图片能被检索的关键
                "html": None,
                "image_path": b.get("image") or None,
                "page": b.get("page"),
                "bbox": _fmt_bbox(b.get("bbox")),
            })
            continue

        if btype == "table":
            flush()
            caption = _clean(b.get("caption") or "")
            body = _clean(b.get("text") or "")
            text = "\n".join(x for x in [caption, body] if x)
            chunks.append({
                "id": f"{doc_id}-c{len(chunks):04d}",
                "idx": len(chunks),
                "kind": "table",
                "section": section.path,
                "text": text,
                "html": b.get("html") or None,
                "image_path": b.get("image") or None,
                "page": b.get("page"),
                "bbox": _fmt_bbox(b.get("bbox")),
            })
            continue

        # 普通正文
        piece = _clean(b.get("text") or "")
        if not piece:
            continue
        if buf_meta["page"] is None:
            buf_meta["page"] = b.get("page")
            buf_meta["bbox"] = b.get("bbox")
            buf_meta["section"] = buf_meta["section"] or section.path
        if sum(len(x) for x in buf) + len(piece) > config.MAX_CHUNK_CHARS:
            flush()
            buf_meta["page"] = b.get("page")
            buf_meta["bbox"] = b.get("bbox")
            buf_meta["section"] = section.path
        buf.append(piece)

    flush()
    return chunks


def _fmt_bbox(bbox: Any) -> str:
    if not bbox:
        return ""
    try:
        return ",".join(f"{float(x):.3f}" for x in bbox[:4])
    except (TypeError, ValueError):
        return ""


def search_text(chunk: Dict[str, Any]) -> str:
    """送进 ES 的文本：章节路径 + 正文/图注，图注额外加权在 mapping 里做。"""
    parts = [chunk.get("section") or "", chunk.get("text") or ""]
    if chunk.get("kind") == "image":
        parts.append("图片 图表 示意图")
    elif chunk.get("kind") == "table":
        parts.append("表格 数据")
    return "\n".join(p for p in parts if p)
