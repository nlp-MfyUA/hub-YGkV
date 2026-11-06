"""楼道消防安全隐患识别：图片预处理、调用 DeepSeek 视觉模型、结果归一化。"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_IMAGE_MB = 10
MAX_IMAGE_SIDE = 1280
MAX_IMAGE_PIXELS = 40_000_000
MAX_OUTPUT_TOKENS = 2000
REQUEST_TIMEOUT_SECONDS = 120.0
ALLOWED_LEVELS = ("高风险", "中风险", "低风险", "无风险", "非楼道")

# 收紧 Pillow 的解压炸弹阈值，超过后由下面显式校验拦截。
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

SYSTEM_PROMPT = """你是一名专业的消防隐患排查专家，负责根据照片判断住宅楼道的消防安全隐患等级。

等级标准：
- 高风险：画面中出现电动车、电瓶（电池）、飞线充电等可能直接起火的元素。
- 中风险：大量堆积物严重影响通行，或堆放大量纸箱、木质家具等可燃物，可能造成火势蔓延。
- 低风险：存在楼道堆物现象，但数量少、体量小，不影响正常通行。
- 无风险：楼道干净整洁，没有堆放物品。
- 非楼道：画面与住宅楼道无关（如风景、人物、办公场所、商品图、示意图等）。

判断规则：
1. 先判断场景是否为住宅楼道。若不是楼道，level 必须为"非楼道"，risks 为空数组。
2. 若是楼道，只输出一个等级，不要输出多个。
3. 多个隐患同时存在时，按最严重的等级输出（高风险优先于中风险，中风险优先于低风险）。
4. risks 用简短中文短语描述画面中可见的隐患，最多 6 条；没有隐患时为空数组。
5. 只输出 JSON，不要输出 Markdown 代码块或额外解释。

输出格式：
{"scene":"楼道或非楼道","risks":["隐患点"],"level":"高风险/中风险/低风险/无风险/非楼道","reason":"一句话说明判断依据"}"""

USER_PROMPT = "请识别这张照片中的楼道消防安全隐患，严格按要求的 JSON 格式输出。"

LEVEL_ALIASES = {
    "高风险": "高风险",
    "高": "高风险",
    "high": "高风险",
    "中风险": "中风险",
    "中等风险": "中风险",
    "中": "中风险",
    "medium": "中风险",
    "低风险": "低风险",
    "低": "低风险",
    "low": "低风险",
    "无风险": "无风险",
    "无隐患": "无风险",
    "安全": "无风险",
    "none": "无风险",
    "非楼道": "非楼道",
    "不是楼道": "非楼道",
    "非住宅楼道": "非楼道",
}

NON_HALLWAY_HINTS = ("非楼道", "不是楼道", "与楼道无关", "非住宅楼道")


class AnalyzeError(Exception):
    """带 HTTP 状态码的业务异常。"""

    status_code = 502


class ImageError(AnalyzeError):
    status_code = 400


class ConfigError(AnalyzeError):
    status_code = 503


class UpstreamError(AnalyzeError):
    status_code = 502


class OutputError(AnalyzeError):
    status_code = 502


def api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def base_url() -> str:
    return os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL


def model_name() -> str:
    return os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def max_image_bytes() -> int:
    try:
        mb = float(os.getenv("MAX_IMAGE_MB", str(DEFAULT_MAX_IMAGE_MB)))
    except ValueError:
        mb = DEFAULT_MAX_IMAGE_MB
    return int(max(mb, 1) * 1024 * 1024)


def chat_completions_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def prepare_image(data: bytes) -> str:
    """校验并压缩图片，返回 data URI。只处理内存数据，不落盘。"""
    if not data:
        raise ImageError("上传的文件为空，请重新选择图片。")
    if len(data) > max_image_bytes():
        raise ImageError(f"图片超过 {max_image_bytes() // (1024 * 1024)}MB 限制，请压缩后重试。")

    try:
        with Image.open(io.BytesIO(data)) as raw:
            if raw.width * raw.height > MAX_IMAGE_PIXELS:
                raise ImageError("图片分辨率过高，请缩小后重试。")
            image = ImageOps.exif_transpose(raw)
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85, optimize=True)
    except ImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageError("无法解析该图片，请上传 JPG、PNG 或 WebP 格式的照片。") from exc

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def parse_model_output(text: str) -> dict[str, Any]:
    """从模型回复中提取 JSON 对象，兼容代码块包裹或前后缀说明。"""
    if not text or not text.strip():
        raise OutputError("模型未返回识别结果（可能被截断），请重试。")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise OutputError("模型返回的内容不是有效 JSON，请重试。")
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OutputError("模型返回的 JSON 无法解析，请重试。") from exc
    if not isinstance(obj, dict):
        raise OutputError("模型返回的结果格式不正确，请重试。")
    return obj


def _clean_text(value: Any, limit: int = 300) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _normalize_level(value: Any) -> str | None:
    text = _clean_text(value, 20)
    if not text:
        return None
    if text in ALLOWED_LEVELS:
        return text
    return LEVEL_ALIASES.get(text.lower()) or LEVEL_ALIASES.get(text)


def _normalize_risks(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    risks: list[str] = []
    for item in value:
        text = _clean_text(item, 80)
        if text and text not in risks:
            risks.append(text)
        if len(risks) >= 6:
            break
    return risks


def normalize_result(obj: dict[str, Any], elapsed_ms: int, model: str) -> dict[str, Any]:
    scene = _clean_text(obj.get("scene"), 40) or "楼道"
    reason = _clean_text(obj.get("reason")) or "模型未提供判断理由。"
    risks = _normalize_risks(obj.get("risks"))
    level = _normalize_level(obj.get("level"))

    non_hallway = any(hint in scene for hint in NON_HALLWAY_HINTS) or level == "非楼道"
    if non_hallway:
        scene = "非楼道"
        level = "非楼道"
        risks = []

    if level is None:
        raise OutputError("模型未给出有效的风险等级，请重试或换一张更清晰的照片。")

    return {
        "level": level,
        "scene": scene,
        "risks": risks,
        "reason": reason,
        "elapsed_ms": elapsed_ms,
        "model": model,
    }


def _extract_error(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except ValueError:
        return f"模型服务返回 HTTP {resp.status_code}。"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:300]
        if payload.get("message"):
            return str(payload["message"])[:300]
    return f"模型服务返回 HTTP {resp.status_code}。"


async def analyze_image(image_bytes: bytes) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise ConfigError(
            "未配置 DEEPSEEK_API_KEY。请在环境变量或 .env 中设置后重启服务。"
        )

    data_uri = prepare_image(image_bytes)
    model = model_name()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": USER_PROMPT},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }

    started = time.perf_counter()
    response: httpx.Response | None = None
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            try:
                response = await client.post(
                    chat_completions_url(base_url()),
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                raise UpstreamError("模型响应超时，请稍后重试。") from exc
            except httpx.HTTPError as exc:
                raise UpstreamError("无法连接模型服务，请检查网络后重试。") from exc

            if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(1.5)
                continue
            break

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response is None:
        raise UpstreamError("模型服务未返回响应，请稍后重试。")
    if response.status_code != 200:
        raise UpstreamError(f"模型调用失败：{_extract_error(response)}")

    try:
        body = response.json()
        message = body["choices"][0]["message"]
        content = message.get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise UpstreamError("模型服务返回的数据结构异常，请重试。") from exc

    if not content.strip():
        if message.get("reasoning_content"):
            raise UpstreamError("模型只返回了推理过程，未给出结论，请重试。")
        raise UpstreamError("模型未返回有效结果，请重试。")

    obj = parse_model_output(content)
    return normalize_result(obj, elapsed_ms, model)
