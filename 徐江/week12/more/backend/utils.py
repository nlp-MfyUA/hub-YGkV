"""工具层：图片校验 / Base64 编码 / JSON 容错解析（功能设计文档 F-05、F-07）。

错误码矩阵（功能设计文档 §5）：
- unsupported_image_type  422  格式不支持
- image_too_large         413  超过大小
- image_too_small         422  尺寸过小
- model_timeout           504  模型超时
- model_upstream_error    502  模型 5xx
- model_output_unparseable 502 输出非 JSON
- invalid_enum            502  枚举越界
- provider_not_configured 503  未配置密钥
"""
from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

from PIL import Image

from .errors import (
    ImageTooLargeError,
    ImageTooSmallError,
    ModelOutputUnparseableError,
    UnsupportedImageTypeError,
)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def validate_image(data: bytes, content_type: str | None, *,
                   max_mb: int = 8, min_side: int = 224) -> tuple[int, int]:
    """按 存在性 → MIME → 大小 → Pillow 尺寸 的顺序校验，返回 (宽, 高)。"""
    if not data:
        raise UnsupportedImageTypeError("上传内容为空")

    # 1) MIME（content_type 缺失时不拦截，交给 Pillow 嗅探兜底）
    if content_type and content_type.lower() not in ALLOWED_MIME:
        raise UnsupportedImageTypeError(
            f"不支持的图片格式 {content_type}，请上传 JPEG/PNG/WebP"
        )

    # 2) 大小
    if len(data) > max_mb * 1024 * 1024:
        raise ImageTooLargeError(
            f"图片大小 {len(data) / 1024 / 1024:.1f} MB，超过上限 {max_mb} MB，请重拍"
        )

    # 3) Pillow 尺寸 + 格式复核
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            fmt = im.format or ""
            width, height = im.size
    except Exception as exc:  # 非图片字节流
        raise UnsupportedImageTypeError(f"无法解析图片内容：{exc}") from exc

    if fmt not in ALLOWED_FORMATS:
        raise UnsupportedImageTypeError(
            f"不支持的图片格式 {fmt or '未知'}，请上传 JPEG/PNG/WebP"
        )
    if min(width, height) < min_side:
        raise ImageTooSmallError(
            f"图片尺寸 {width}x{height}，短边不足 {min_side} px，请重拍"
        )
    return width, height


def encode_image(data: bytes) -> str:
    """bytes → Base64 字符串（data URL 的组装在 provider 内完成）。"""
    return base64.b64encode(data).decode("ascii")


_FENCE_HEAD = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_FENCE_TAIL = re.compile(r"\s*```$")


def parse_model_json(text: str) -> dict[str, Any]:
    """模型输出容错解析（技术设计文档 §7）。

    1. 去首尾空白 → 2. 剥离 ``` 围栏 → 3. 截取首个 { 至末个 } → 4. json.loads。
    任一步失败抛 ModelOutputUnparseableError（上层映射 502）。
    """
    if not text or not text.strip():
        raise ModelOutputUnparseableError("模型返回为空")

    s = text.strip()
    s = _FENCE_HEAD.sub("", s)
    s = _FENCE_TAIL.sub("", s)
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j == -1 or j <= i:
        raise ModelOutputUnparseableError("模型输出中未找到 JSON 对象")

    try:
        obj = json.loads(s[i : j + 1])
    except json.JSONDecodeError as exc:
        raise ModelOutputUnparseableError(f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行）") from exc

    if not isinstance(obj, dict):
        raise ModelOutputUnparseableError("模型输出不是 JSON 对象")
    return obj
