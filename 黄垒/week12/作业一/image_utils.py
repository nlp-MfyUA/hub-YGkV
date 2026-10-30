"""图片预处理：校验格式、纠正方向、压缩尺寸。

手机拍出来的照片动辄 4-8MB，直接 base64 发给模型既慢又贵；
统一压到长边 1280、JPEG 质量 85，通常能到 200KB 以内，识别效果基本无损。
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# 允许的格式。iPhone 默认拍 HEIC，装上 pillow-heif 就能直接读；
# 没装时会在下面给出明确的格式错误提示。
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "BMP", "GIF"}
try:  # 可选依赖，不影响其它格式
    from pillow_heif import register_heif_opener

    register_heif_opener()
    ALLOWED_FORMATS.update({"HEIF", "HEIC"})
except ImportError:
    pass

# 限制解码像素数，避免超大图片把内存打满
Image.MAX_IMAGE_PIXELS = 40_000_000

MAX_SIDE = 1280
JPEG_QUALITY = 85


class ImageError(ValueError):
    """图片不合法（格式 / 损坏 / 过大）。"""


def prepare_image(raw: bytes, max_bytes: int = 10 * 1024 * 1024) -> tuple[bytes, str, str]:
    """返回 (jpeg 字节, mime, "宽x高")。"""
    if not raw:
        raise ImageError("上传的图片为空")
    if len(raw) > max_bytes:
        raise ImageError(f"图片超过 {max_bytes // 1024 // 1024}MB 上限，请压缩后再上传")

    try:
        with Image.open(io.BytesIO(raw)) as image:
            fmt = (image.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ImageError(f"不支持的图片格式：{fmt or '未知'}，请上传 JPG / PNG / WEBP")

            # 手机照片的 EXIF 里有旋转信息，不纠正的话模型会看到「躺着」的楼道
            image = ImageOps.exif_transpose(image)
            image = _flatten_alpha(image)
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            size_text = f"{image.width}x{image.height}"
            return buffer.getvalue(), "image/jpeg", size_text
    except ImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageError("图片像素过大，请压缩后再上传") from exc
    except UnidentifiedImageError as exc:
        raise ImageError("无法识别的图片文件，请上传 JPG / PNG / WEBP") from exc
    except OSError as exc:
        raise ImageError(f"图片读取失败：{exc}") from exc


def _flatten_alpha(image: Image.Image) -> Image.Image:
    """PNG 的透明通道转成白底，避免保存成 JPEG 时背景变黑。"""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")
