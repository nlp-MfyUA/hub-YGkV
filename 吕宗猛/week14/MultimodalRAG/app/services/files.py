"""Upload storage and MinerU ZIP result handling."""
import io
import mimetypes
import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote

from app.core.config import get_settings

settings = get_settings()
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
IMG_TAG_RE = re.compile(r"!\[([^\]]*)\]\((?:<)?(?:\./)?images/([^)>\s]+)(?:>)?(?:\s+\"[^\"]*\")?\)")
IMG_SRC_RE = re.compile(r'''<img[^>]+src=["'](?:\./)?images/([^"']+)["']''', re.IGNORECASE)


def safe_file_name(name: str) -> str:
    name = (name or "file").replace("\\", "/").split("/")[-1].strip()
    return name or "file"


def save_upload(content: bytes, original_name: str) -> tuple[Path, int]:
    settings.ensure_dirs()
    name = safe_file_name(original_name)
    suffix = Path(name).suffix.lower() or ".bin"
    target = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(content)
    return target, len(content)


def save_chat_image(content: bytes, original_name: str) -> Path:
    settings.ensure_dirs()
    name = safe_file_name(original_name)
    suffix = Path(name).suffix.lower() or ".png"
    target = settings.chat_upload_dir / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(content)
    return target


def image_url(doc_id: int, file_name: str) -> str:
    return f"/api/documents/{doc_id}/images/{quote(file_name)}"


def _pick_markdown(zf: zipfile.ZipFile) -> str:
    names = [n for n in zf.namelist() if n.lower().endswith(".md") and not n.endswith("/")]
    if not names:
        raise ValueError("MinerU ZIP 内没有 markdown 文件")
    preferred = [n for n in names if Path(n).name.lower() in {"full.md", "markdown.md"}]
    pool = preferred or names
    pool.sort(key=lambda n: (len(Path(n).parts), len(n)))
    return zf.read(pool[0]).decode("utf-8", "replace")


def save_mineru_zip(doc_id: int, data: bytes) -> tuple[str, list[dict]]:
    """Extract markdown + images from MinerU result ZIP and rewrite image links."""
    settings.ensure_dirs()
    out_dir = settings.parsed_dir / str(doc_id)
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        markdown = _pick_markdown(zf)
        saved: list[dict] = []
        used: set[str] = set()
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            lower = name.lower()
            suffix = Path(name).suffix.lower()
            if "images/" not in lower and suffix not in IMAGE_EXTS:
                continue
            if suffix not in IMAGE_EXTS:
                continue
            base = safe_file_name(name)
            candidate = base
            i = 1
            while candidate in used:
                candidate = f"{Path(base).stem}_{i}{Path(base).suffix}"
                i += 1
            used.add(candidate)
            payload = zf.read(name)
            (image_dir / candidate).write_bytes(payload)
            mime = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
            saved.append({
                "file_name": candidate,
                "file_path": str(image_dir / candidate),
                "mime_type": mime,
                "size": len(payload),
            })

    def repl(match: re.Match) -> str:
        alt, raw_name = match.group(1), match.group(2)
        name = Path(unquote(raw_name)).name
        return f"![{alt or '图片'}]({image_url(doc_id, name)})"

    markdown = IMG_TAG_RE.sub(repl, markdown)
    markdown = IMG_SRC_RE.sub(lambda m: f'src="{image_url(doc_id, Path(unquote(m.group(1))).name)}"', markdown)
    (out_dir / "document.md").write_text(markdown, encoding="utf-8")
    return markdown, saved
