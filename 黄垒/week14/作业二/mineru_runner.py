#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MinerU 调用与输出归一化。

为什么不在 worker 里直接 `mineru-kit parse`（本地模式）：
  本地模式每次都要重新加载 MinerU2.5 的 VLM（实测 46s 起步），
  批量解析时这部分开销被放大 N 倍。所以常驻一个 `mineru-kit api-server`，
  worker 通过 `--remote-url` 走 HTTP 提交，模型只加载一次。

输出格式（mineru 4.1.7，zip 包）：
  markdown.md               给人看的 markdown
  structured_content.json   按页组织的块（本文件主要消费这个）
  middle_json.json          中间态，带更细的 bbox
  images/                   从 PDF 里裁出来的图

structured_content.json 的块长这样：
  {"type":"image","sub_type":"flowchart","bbox":[...],
   "content":"<VLM 生成的图注>","captions":[],"image_source":"images/page_0_image_1.jpg"}
  {"type":"text","content":"...","text_level":1,...}
"""

import html
import json
import logging
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config

log = logging.getLogger("mineru")

_TEXT_TYPES = {"text", "list", "code", "equation", "interline_equation",
               "aside_text", "abstract", "reference", "index"}
_TITLE_TYPES = {"title", "doc_title", "paragraph_title", "section_title", "heading"}
_SKIP_TYPES = {"header", "footer", "page_number", "page_footnote", "discarded"}


class MineruError(RuntimeError):
    pass


# ---------------------------------------------------------------- 调 CLI
def _build_cmd(pdf_path: str, zip_path: str) -> List[str]:
    cmd = [config.MINERU_BIN, "parse", pdf_path,
           "--format", "zip", "-o", zip_path,
           "--tier", config.MINERU_TIER]
    if config.MINERU_REMOTE_URL:
        cmd += ["--remote-url", config.MINERU_REMOTE_URL]
    return cmd


def run_mineru(pdf_path: str, work_dir: Path) -> Tuple[Path, str, float]:
    """跑一次解析，返回 (zip 路径, 引擎名, 耗时)。失败抛 MineruError。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / "result.zip"
    if zip_path.exists():
        zip_path.unlink()
    cmd = _build_cmd(str(pdf_path), str(zip_path))
    t0 = time.time()
    log_path = work_dir / "mineru.log"
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write("$ " + " ".join(cmd) + "\n")
        lf.flush()
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                              timeout=config.MINERU_TIMEOUT, env=env)
    cost = time.time() - t0
    engine = "remote" if config.MINERU_REMOTE_URL else "local"
    if proc.returncode != 0 or not zip_path.exists():
        tail = _tail(log_path, 1200)
        raise MineruError(f"mineru-kit 退出码 {proc.returncode}\n{tail}")
    return zip_path, engine, cost


def _tail(path: Path, n: int) -> str:
    try:
        data = path.read_text("utf-8", "replace")
    except OSError:
        return "(no log)"
    # 去掉进度条那些 \r 覆盖行，只留最后 n 个字符
    clean = "\n".join(line for line in re.split(r"[\r\n]+", data) if line.strip())
    return clean[-n:]


# ---------------------------------------------------------------- 解包 + 归一化
def _extract(zip_path: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return dest


def _find(dest: Path, name: str) -> Optional[Path]:
    hit = list(dest.rglob(name))
    return hit[0] if hit else None


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return " ".join(_as_text(x) for x in v)
    if isinstance(v, dict):
        for k in ("content", "text", "value"):
            if k in v:
                return _as_text(v[k])
        return ""
    return str(v)


def _strip_html(s: str) -> str:
    """表格 html → 可检索文本：单元格之间用 ` | `，行之间用换行。"""
    if not s:
        return ""
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = re.sub(r"(?i)</tr>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    lines = [re.sub(r"(\s*\|\s*)+", " | ", ln).strip(" |").strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


_MERMAID_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_MERMAID_LABEL = re.compile(r'"([^"]{2,200})"')


def _flowchart_text(content: str) -> str:
    """MinerU 对流程图会给一段 mermaid。把里面的节点标签抽成一句人话，
    比把 mermaid 语法原样塞进索引好得多（BM25 只认词，不认 `-->`）。"""
    body = _MERMAID_FENCE.sub("", content or "").strip()
    labels = [re.sub(r"\\n", " ", m) for m in _MERMAID_LABEL.findall(body)]
    if labels:
        # 去重保序
        seen, uniq = set(), []
        for x in labels:
            x = x.strip()
            if x and x not in seen:
                seen.add(x)
                uniq.append(x)
        return "流程图：" + "；".join(uniq[:20])
    return body


def _scale_bbox(bbox: Any) -> Optional[List[float]]:
    """MinerU 新版给的是 0~1 归一化坐标，老版给的是像素；统一成 4 位小数。"""
    if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        vals = [round(float(x), 4) for x in bbox[:4]]
    except (TypeError, ValueError):
        return None
    if max(vals) > 2:            # 像素坐标 → 归一化
        return None
    return vals


def _norm_block(b: Dict[str, Any], page_idx: int) -> Optional[Dict[str, Any]]:
    """把 structured_content 的块统一成内部结构。"""
    btype = (b.get("type") or "").lower()
    if btype in _SKIP_TYPES:
        return None
    content = _as_text(b.get("content"))
    captions = _as_text(b.get("captions") or b.get("image_caption") or b.get("table_caption"))
    footnote = _as_text(b.get("footnotes") or b.get("image_footnote") or b.get("table_footnote"))
    img = (b.get("image_source") or b.get("img_path") or b.get("image_path") or "")
    if isinstance(img, list):
        img = img[0] if img else ""
    level = b.get("text_level") or b.get("level") or 0
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 0
    bbox = _scale_bbox(b.get("bbox"))

    if btype in _TITLE_TYPES:
        if not content.strip():
            return None
        return {"type": "text", "text": content, "caption": "", "footnote": "",
                "image": "", "page": page_idx, "bbox": bbox,
                "level": max(1, level or 1), "sub_type": btype}

    if btype == "table":
        body = content if content.lstrip().startswith("<") else ""
        text = _strip_html(body) if body else content
        if captions:
            text = f"{captions}\n{text}"
        return {"type": "table", "text": text, "html": body,
                "caption": captions, "footnote": footnote, "image": img,
                "page": page_idx, "bbox": bbox, "level": 0,
                "sub_type": b.get("sub_type") or ""}

    if btype == "image":
        sub = (b.get("sub_type") or "").lower()
        text = content
        if "```" in text or sub in ("flowchart", "diagram", "chart"):
            text = _flowchart_text(text)
        if captions:
            text = f"{captions}\n{text}"
        return {"type": "image", "text": text, "caption": captions,
                "footnote": footnote, "image": img, "page": page_idx,
                "bbox": bbox, "level": 0, "sub_type": sub}

    if btype in _TEXT_TYPES or content:
        if not content.strip():
            return None
        return {"type": "text", "text": content, "caption": "", "footnote": "",
                "image": "", "page": page_idx, "bbox": bbox,
                "level": 0, "sub_type": btype}
    return None


def load_blocks(dest: Path) -> Tuple[List[Dict[str, Any]], int]:
    """读 structured_content.json；没有就退回 middle_json.json。"""
    src = _find(dest, "structured_content.json") or _find(dest, "middle_json.json")
    if not src:
        raise MineruError("MinerU 输出里找不到 structured_content.json")
    doc = json.loads(src.read_text("utf-8"))
    pages = doc.get("pages") or []
    blocks: List[Dict[str, Any]] = []
    for p in pages:
        pidx = int(p.get("page_idx", 0))
        for b in p.get("blocks") or []:
            nb = _norm_block(b, pidx)
            if nb:
                blocks.append(nb)
    page_count = int(((doc.get("metadata") or {}).get("document") or {}).get("page_count")
                     or len(pages) or 0)
    return blocks, page_count


def save_images(dest: Path, blocks: List[Dict[str, Any]], doc_id: str) -> int:
    """把图片搬到对外静态目录，块里的 image 字段改写成相对路径 doc_id/xxx.jpg。"""
    out_dir = config.MEDIA_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for b in blocks:
        src_rel = b.get("image") or ""
        if not src_rel:
            continue
        src = dest / src_rel
        if not src.exists():
            # 有些版本图片路径是相对 md 所在目录的
            cand = list(dest.rglob(Path(src_rel).name))
            if not cand:
                b["image"] = ""
                continue
            src = cand[0]
        name = f"{n:03d}_{Path(src).name}"
        shutil.copyfile(src, out_dir / name)
        b["image"] = f"{doc_id}/{name}"
        n += 1
    return n


def parse_pdf(pdf_path: str, doc_id: str) -> Dict[str, Any]:
    """完整流程：调 MinerU → 解包 → 归一化 → 搬图片。"""
    work_dir = config.WORK_DIR / doc_id
    zip_path, engine, cost = run_mineru(pdf_path, work_dir)
    dest = _extract(zip_path, work_dir / "extract")
    blocks, pages = load_blocks(dest)
    n_images = save_images(dest, blocks, doc_id)
    md = _find(dest, "markdown.md")
    markdown = md.read_text("utf-8", "replace") if md else ""
    log.info("解析完成 doc=%s pages=%s blocks=%s images=%s 耗时=%.1fs",
             doc_id, pages, len(blocks), n_images, cost)
    return {"blocks": blocks, "pages": pages, "n_images": n_images,
            "engine": engine, "seconds": cost, "markdown": markdown,
            "work_dir": str(work_dir)}
