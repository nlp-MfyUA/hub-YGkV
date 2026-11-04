"""用户上传的图片在内存中校验与压缩，不保存到磁盘。"""
import io

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def to_jpeg(raw: bytes) -> bytes:
    if not raw:
        raise HTTPException(400, "图片不能为空，请重新选择")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, "图片不能超过 8 MB")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(400, "只支持 JPG、PNG、WebP 格式")
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(400, "图片像素过大，请压缩后重试")
            image.load()
            image = ImageOps.exif_transpose(image)
            # 透明 PNG 合成在白色背景上，防止 RGBA 直接转 JPEG 发生问题。
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                white = Image.new("RGB", rgba.size, "white")
                white.paste(rgba, mask=rgba.getchannel("A"))
                image = white
            else:
                image = image.convert("RGB")
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=86, optimize=True)
            return out.getvalue()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, "图片文件损坏或无法识别") from exc
