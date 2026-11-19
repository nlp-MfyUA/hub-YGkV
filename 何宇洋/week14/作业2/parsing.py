import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from embeddings import encode
from settings import EMBEDDING_MODEL, MINERU_TIER, MINERU_TIMEOUT

IMAGE_PATTERN = re.compile(r"!\[[^\n]*?\]\([^\n]*?\)")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def document_chunks(output):
    content = json.loads((output / "structured_content.json").read_text(encoding="utf-8"))
    for page in content["pages"]:
        page_number = page["page_idx"] + 1
        blocks = page["blocks"]
        body = [IMAGE_PATTERN.sub("", block.get("content", "")).strip() for block in blocks]
        text = "\n\n".join(part for part in body if part)
        for start in range(0, len(text), 380):
            yield page_number, text[start:start + 450], []
            if start + 450 >= len(text):
                break
        for index, block in enumerate(blocks):
            source = unquote(block.get("image_source") or "")
            path = (output / source).resolve()
            if (not source or not path.is_relative_to(output / "images")
                    or path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file()):
                continue
            annotations = [
                item["content"] for key in ("captions", "footnotes") for item in block.get(key, [])
                if item.get("content")
            ]
            nearby = " ".join(body[max(0, index - 1):index + 2]).strip()
            description = "\n".join(annotations) or nearby or "本页包含图片"
            yield page_number, description[:450], [path.relative_to(output).as_posix()]


def parse_pdf(payload, output):
    output.mkdir()
    source = output / "input.pdf"
    archive_path = output / "mineru.zip"
    source.write_bytes(payload)
    # The console script may be outside PATH when launched with the Conda interpreter directly.
    fallback = Path(sys.executable).parent / "Scripts" / "mineru-kit.exe"
    command = [
        shutil.which("mineru-kit") or str(fallback),
        "parse", str(source), "--output", str(archive_path),
        "--format", "zip", "--tier", MINERU_TIER, "--pages", "all", "--ocr-mode", "auto",
        "--disable-image-analysis",
    ]
    with (output / "mineru.log").open("wb") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=MINERU_TIMEOUT)
    with ZipFile(archive_path) as archive:
        archive.extractall(output)
    source.unlink()
    archive_path.unlink()

    chunks = list(document_chunks(output))
    if not chunks:
        raise ValueError("MinerU 没有提取到可检索的文字或图片")
    vectors = encode([body for _, body, _ in chunks])
    return [
        (page, body, images, EMBEDDING_MODEL, vector.tobytes())
        for (page, body, images), vector in zip(chunks, vectors, strict=True)
    ]
