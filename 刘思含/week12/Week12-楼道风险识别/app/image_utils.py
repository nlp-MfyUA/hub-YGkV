"""图片预处理。

手机照片的三个坑：
1. EXIF 方向不对 -> 竖拍照片变横躺，必须 exif_transpose
2. 体积大（3-12MB）-> base64 后膨胀 33%，容易 413/超时，必须压缩
3. 文件名不可信 -> uuid 重命名，防止路径穿越
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

MAX_EDGE = 1280
JPEG_QUALITY = 85

UPLOAD_DIR = Path("data/uploads")
ANNOTATED_DIR = Path("data/annotated")


class ImageProcessError(ValueError):
    """图片无法解码或不合法。"""


def load_image(raw: bytes) -> Image.Image:
    """从字节流读出图片，并纠正手机拍摄方向。"""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001 - PIL 的异常类型很杂
        raise ImageProcessError("无法解析图片，请上传 JPG/PNG/WEBP 格式") from exc

    img = ImageOps.exif_transpose(img)  # 手机竖拍的旋转信息在这里被应用
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def preprocess(raw: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """统一转成压缩后的 JPEG 字节，用于 base64 上传给模型。"""
    img = load_image(raw)
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def save_upload(raw: bytes) -> tuple[str, Path]:
    """保存原始上传图，返回 (对外访问的 URL, 本地路径)。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    path = UPLOAD_DIR / name
    img = load_image(raw)
    img.save(path, format="JPEG", quality=92)
    return f"/media/uploads/{name}", path


def save_annotated(upload_url: str, boxes: list[list[float]]) -> str | None:
    """把模型给的归一化框画到原图上，返回标注图 URL。

    boxes 形如 [[x1, y1, x2, y2], ...]，取值 0-1。解析不出来就返回 None，
    标注是可选的增强功能，失败不影响主流程。
    """
    if not boxes:
        return None

    src = UPLOAD_DIR / Path(upload_url).name
    if not src.exists():
        return None

    try:
        img = Image.open(src).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        width = max(3, int(min(w, h) * 0.006))
        try:
            font = ImageFont.truetype("simhei.ttf", max(16, int(min(w, h) * 0.035)))
        except OSError:
            font = ImageFont.load_default()

        for i, box in enumerate(boxes):
            if len(box) != 4:
                continue
            x1, y1, x2, y2 = box
            rect = [x1 * w, y1 * h, x2 * w, y2 * h]
            draw.rectangle(rect, outline=(216, 52, 47), width=width)
            draw.text((rect[0] + 6, rect[1] + 4), f"# {i + 1}", fill=(216, 52, 47), font=font)

        ANNOTATED_DIR.mkdir(parents=True, exist_ok=True)
        name = f"ann_{src.stem}.jpg"
        img.save(ANNOTATED_DIR / name, format="JPEG", quality=88)
        return f"/media/annotated/{name}"
    except Exception:  # noqa: BLE001
        return None
