"""Markdown-aware chunking that preserves image references."""
import re
from pathlib import Path
from urllib.parse import unquote

MAX_CHARS = 1200
OVERLAP = 100
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
IMAGE_URL_RE = re.compile(r"/api/documents/\d+/images/([^)\s]+)")


def _split_sections(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        if HEADING_RE.match(line) and current:
            sections.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [s for s in sections if s]


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > MAX_CHARS:
            if buf:
                chunks.append(buf)
                buf = ""
            start = 0
            while start < len(para):
                chunks.append(para[start:start + MAX_CHARS])
                start += max(1, MAX_CHARS - OVERLAP)
            continue
        if len(buf) + len(para) + 2 <= MAX_CHARS:
            buf = f"{buf}\n\n{para}".strip() if buf else para
        else:
            if buf:
                chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks


def _image_ids(content: str, image_id_by_name: dict[str, int]) -> list[int]:
    result: list[int] = []
    for raw in IMAGE_URL_RE.findall(content):
        name = unquote(raw).split("/")[-1]
        image_id = image_id_by_name.get(name)
        if image_id and image_id not in result:
            result.append(image_id)
    return result


def chunk_markdown(markdown: str, image_id_by_name: dict[str, int]) -> list[dict]:
    chunks: list[dict] = []
    for section in _split_sections(markdown):
        for piece in _split_long(section):
            content = piece.strip()
            if not content:
                continue
            chunks.append({
                "chunk_index": len(chunks),
                "content": content,
                "token_count": max(1, int(len(content) / 2)),
                "image_ids": _image_ids(content, image_id_by_name),
            })
    return chunks
