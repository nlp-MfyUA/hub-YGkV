"""Provider 连通性自检（功能设计文档 F-12）。

用法：
    python scripts/check_provider.py --provider deepseek

行为：程序生成一张 64×64 纯灰 JPEG，发起一次最小请求，
打印 HTTP 状态（体现在错误信息中）、耗时、原始返回前 500 字符。
失败时打印诊断建议：检查 base_url / model / api_key，或切换 provider。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image

from backend.config import get_settings
from backend.errors import ApiError
from backend.prompt import SYSTEM_PROMPT, USER_TEXT
from backend.providers import build_provider


def make_gray_jpeg_b64(size: int = 64) -> str:
    """生成一张纯灰测试图（64×64），返回 Base64。"""
    img = Image.new("RGB", (size, size), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def check(provider_name: str | None) -> int:
    settings = get_settings()
    if provider_name:
        settings = settings.model_copy(update={"vision_provider": provider_name})

    print(f"== 连通性自检 provider={settings.vision_provider} "
          f"model={settings.active_model} ==")
    print(f"   base_url: {settings.active_base_url or '(未配置)'}")
    print(f"   api_key : {'已配置（' + str(len(settings.active_api_key)) + ' 字符）' if settings.active_api_key else '(未配置)'}")

    if not settings.active_api_key or not settings.active_base_url:
        print("\n[失败] 当前 provider 未配置 api_key / base_url。")
        print("诊断建议：")
        print("  1. 复制 .env.example 为 .env，填写对应通道的密钥；")
        print("  2. 或加 --provider 参数切换到另一通道（deepseek / qwen）。")
        return 2

    try:
        provider = build_provider(settings)
    except Exception as exc:
        print(f"\n[失败] provider 构造失败：{exc}")
        print("诊断建议：检查 .env 中该通道的 api_key / base_url 是否为空。")
        return 2

    b64 = make_gray_jpeg_b64()
    t0 = time.perf_counter()
    try:
        raw = await provider.analyze(b64, SYSTEM_PROMPT, USER_TEXT)
    except ApiError as exc:
        print(f"\n[失败] 模型调用未通过（耗时 {(time.perf_counter() - t0) * 1000:.0f} ms）")
        print(f"   错误码：{exc.error_code}")
        print(f"   详情：{exc.detail}")
        print("\n诊断建议：")
        print(f"  1. 检查 base_url 是否正确（当前 {settings.active_base_url}）；")
        print(f"  2. 检查 model 是否可用（当前 {settings.active_model}）；")
        print("  3. 检查 api_key 是否有效、是否欠费；")
        print("  4. 尝试切换通道：--provider qwen 或 --provider deepseek。")
        return 1
    except Exception as exc:  # 未归类异常
        print(f"\n[失败] 未预期错误：{exc!r}")
        return 1

    text = raw.text or ""
    print(f"\n[成功] 模型调用通过（耗时 {raw.latency_ms} ms）")
    print(f"   provider={raw.provider} model={raw.model}")
    print(f"   原始返回前 500 字符：\n{'-' * 40}\n{text[:500]}\n{'-' * 40}")
    if not text.strip().startswith("{"):
        print("注意：返回不是以 { 开头，后端解析器会尝试剥离围栏/截取 JSON，"
              "若解析失败请检查 Prompt 或模型输出设置。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="视觉 Provider 连通性自检")
    parser.add_argument("--provider", default=None, choices=["deepseek", "qwen"],
                        help="覆盖 .env 中的 VISION_PROVIDER")
    args = parser.parse_args()
    sys.exit(asyncio.run(check(args.provider)))


if __name__ == "__main__":
    main()
