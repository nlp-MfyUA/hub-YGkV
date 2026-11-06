"""通过兼容 Chat Completions 的接口调用 DeepSeek Flash 或 Qwen-VL。"""
import base64
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MODEL_PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek V4.1 Flash",
        "key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
        "model_default": "deepseek-flash",
        "base_env": "DEEPSEEK_BASE_URL",
        "base_default": "https://api.deepseek.com",
    },
    "qwen": {
        "label": "Qwen3-VL-Flash",
        "key_env": "QWEN_API_KEY",
        "model_env": "QWEN_MODEL",
        "model_default": "qwen3-vl-flash",
        "base_env": "QWEN_BASE_URL",
        "base_default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
}

PROMPT = """
你是一名住宅楼道消防安全巡检员。请根据用户提供的一张图片，报告你能直接看到的事实。
不要臆测画面外的情况，不要把普通自行车误认成电动车，也不要把普通插座认成飞线充电。
楼道包括住宅的公共走廊、楼梯间、楼梯平台、电梯前室等公共疏散通道。
如果图片不是上述场景，或无法看出是不是公共疏散通道，则 is_corridor=false。
只返回 JSON 对象，不能输出 markdown，不要自行输出风险等级：
{
  "is_corridor": true,
  "electric_vehicle_or_battery": false,
  "unsafe_charging": false,
  "severe_obstruction": false,
  "large_combustible_pile": false,
  "small_clutter": false,
  "description": "一句话客观描述图中场景",
  "evidence": ["画面中直接看到的证据1", "证据2"]
}
字段说明：
electric_vehicle_or_battery：明显可见电动车、电动自行车或可识别的动力电池；
unsafe_charging：可见飞线充电、危险电动车充电接线；
severe_obstruction：大量物品严重堵塞公共通行或疏散路线；
large_combustible_pile：堆积了大量纸箱、木质家具、布料等明显可燃物；
small_clutter：有少量杂物堆放，但没有达到大量堵塞。
没有直接证据时风险字段必须为 false；非楼道时所有风险字段都为 false。
evidence 使用简短、可复核的中文描述；不要把不确定内容写成已确认事实。
""".strip()


class VisionAPIError(Exception):
    """用于向网页返回不含密钥的模型错误信息。"""


def provider_config(provider: str) -> dict:
    if provider not in MODEL_PROVIDERS:
        raise VisionAPIError("未知模型提供商")
    config = MODEL_PROVIDERS[provider]
    return {
        "provider": provider,
        "label": config["label"],
        "model": os.getenv(config["model_env"], config["model_default"]),
        "api_key": os.getenv(config["key_env"], "").strip(),
        "base_url": os.getenv(config["base_env"], config["base_default"]).rstrip("/"),
    }


def provider_status() -> list[dict]:
    """不把用户的真实 API Key 返回给浏览器。"""
    return [
        {
            "id": name,
            "name": provider_config(name)["label"],
            "model": provider_config(name)["model"],
            "configured": bool(provider_config(name)["api_key"]),
        }
        for name in MODEL_PROVIDERS
    ]


def make_payload(jpeg_bytes: bytes, provider: str, model: str) -> dict:
    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "response_format": {"type": "json_object"},
        "max_tokens": 850,
    }
    if provider == "deepseek":
        payload["thinking"] = {"type": "disabled"}
    elif provider == "qwen":
        payload["enable_thinking"] = False
    return payload


async def inspect_image(jpeg_bytes: bytes, provider: str) -> tuple[str, str]:
    """返回 (模型输出的 JSON 文本, 实际使用的 model ID)。"""
    config = provider_config(provider)
    if not config["api_key"]:
        raise VisionAPIError(f"未配置 {config['label']} API Key，请按 README 配置 .env")
    payload = make_payload(jpeg_bytes, provider, config["model"])
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                config["base_url"] + "/chat/completions",
                headers={"Authorization": "Bearer " + config["api_key"]},
                json=payload,
            )
            response.raise_for_status()
            message = response.json()["choices"][0]
            if message.get("finish_reason") == "length":
                raise VisionAPIError("模型输出被截断，请重新识别")
            text = message["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise VisionAPIError("模型未返回有效 JSON，请重试")
            return text, config["model"]
    except httpx.TimeoutException as exc:
        raise VisionAPIError("模型服务响应超时，请稍后重试") from exc
    except httpx.HTTPStatusError as exc:
        raise VisionAPIError(
            f"模型接口返回 HTTP {exc.response.status_code}：请核对 API Key、模型名称和地域地址"
        ) from exc
    except httpx.RequestError as exc:
        raise VisionAPIError("模型服务连接失败，请检查网络或接口地址") from exc
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise VisionAPIError("模型响应结构错误，请重试") from exc
