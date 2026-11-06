# -*- coding: utf-8 -*-
"""
楼道消防风险识别 — 多模态应用后端（Week12 作业1）

参考：02-多模态大模型/案例-多模态内容理解.ipynb
模型：DeepSeek V4.1 Flash（OpenAI 兼容接口，图像理解），经飞牛网关调用
      https://api-docs.deepseek.com/zh-cn/guides/vision

零第三方 SDK 依赖：HTTP 调用走标准库 urllib。

启动：
    python app.py                     # HTTP :8000 + HTTPS :8443（首次自动生成自签名证书）
    python app.py -NoHttps            # 仅 HTTP
"""
import argparse
import asyncio
import base64
import datetime
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "3000"))
MAX_TOKENS_CEILING = int(os.getenv("MAX_TOKENS_CEILING", "12000"))
MAX_RETRY = int(os.getenv("MAX_RETRY", "3"))  # 思维链超预算时的加倍重试次数
ALLOWED_MIME = {"jpeg", "png", "gif", "webp"}
VALID_CATEGORIES = ["高风险", "中风险", "低风险", "无风险", "非楼道"]

# 分类标准沿用课程案例原版提示词，并要求严格 JSON 输出
PROMPT = """你是一个专业消防专家，擅长识别各种风险。请识别图片中的消防安全隐患以及隐患的危险程度，根据楼道中是否存在大量堆积物、堆积物是否可燃以及是否有起火风险，将隐患分级。请仅输出 JSON 对象，不要输出其他内容。

JSON 字段定义：
- "category": 风险类别，字符串，只能取以下五个值之一："高风险"、"中风险"、"低风险"、"无风险"、"非楼道"
- "elements": 识别到的关键元素字符串数组（例如 ["电动车","飞线充电","纸箱","木质家具","杂物"]），没有则输出空数组 []
- "reason": 一句话判定理由，中文，不超过 60 字

分类标准：
- 高风险：楼道中出现电动车、电瓶、飞线充电等可能起火的元素。
- 中风险：楼道中存在大量堆积物严重影响通行，或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物。
- 低风险：存在楼道堆物现象但不严重。
- 无风险：楼道干净，无堆放物品。
- 非楼道：与楼道场景无关的图片。
"""

app = FastAPI(title="楼道消防风险识别", version="1.0")


@app.get("/api/health")
def health():
    return {"status": "ok" if API_KEY else "no_api_key", "model": MODEL_NAME, "base_url": BASE_URL}


class RecognizeRequest(BaseModel):
    image: str  # data:image/jpeg;base64,...


def chat_completion(payload: dict) -> dict:
    """调用 OpenAI 兼容 chat/completions 接口（标准库 urllib，无 SDK 依赖）。"""
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise HTTPException(502, f"模型网关返回 HTTP {e.code}：{body}")
    except Exception as e:
        raise HTTPException(502, f"调用模型失败：{type(e).__name__}: {str(e)[:200]}")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(502, "模型响应不是合法 JSON")


def parse_json_loose(text: str) -> dict:
    """容错解析模型输出：优先直接 json.loads，失败则截取第一个完整 JSON 对象。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, depth = text.find("{"), 0
    if start == -1:
        raise ValueError("输出中不含 JSON 对象")
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("JSON 对象不完整")


@app.post("/api/recognize")
def recognize(req: RecognizeRequest):
    m = re.match(r"^data:image/([a-z0-9.+-]+);base64,(.+)$", req.image, re.I | re.S)
    if not m:
        raise HTTPException(400, "图片格式错误：需要 data:image/xxx;base64,...（支持 JPEG/PNG/GIF/WebP）")
    mime = m.group(1).lower().replace("jpg", "jpeg")
    b64 = m.group(2)
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, f"不支持的图片格式 {mime}，支持 JPEG/PNG/GIF/WebP")
    try:
        raw_img = base64.b64decode(b64, validate=True)
    except Exception:
        raise HTTPException(400, "base64 解码失败")
    if len(raw_img) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"图片过大（{len(raw_img) / 1048576:.1f} MiB），上限 10 MiB")
    if len(raw_img) < 1024:
        raise HTTPException(400, "图片内容过小，疑似无效")
    if not API_KEY:
        raise HTTPException(500, "未配置 DEEPSEEK_API_KEY：请编辑项目根目录 .env 后重启服务")

    t0 = time.time()
    payload = {
        "model": MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/{mime};base64,{b64}", "detail": "high"}},
            ],
        }],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        # 该模型带思维链，max_tokens 过小会导致最终 content 为空，必须留足余量
        "max_tokens": MAX_TOKENS,
    }

    # 思维链预算不足时（finish_reason=length 且正文为空）自动加倍重试。
    # 图片越复杂/越模糊，思维链越长，固定预算必然存在失败率。
    data = None
    reasoning = ""
    for attempt in range(MAX_RETRY):
        data = chat_completion(payload)
        choices = data.get("choices") or []
        if not choices:
            raise HTTPException(502, f"模型未返回结果：{json.dumps(data, ensure_ascii=False)[:200]}")
        msg = choices[0].get("message") or {}
        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or "").strip()
        if content:
            break
        if choices[0].get("finish_reason") == "length" and attempt < MAX_RETRY - 1:
            payload["max_tokens"] = min(payload["max_tokens"] * 2, MAX_TOKENS_CEILING)
            continue
        raise HTTPException(502, f"模型未输出正文（finish_reason={choices[0].get('finish_reason')}），"
                                 f"思维链末尾：{reasoning[-200:]}")

    try:
        obj = parse_json_loose(content)
    except Exception:
        raise HTTPException(502, f"模型输出解析失败，原始输出：{content[:200]}")

    category = str(obj.get("category", "")).strip()
    if category not in VALID_CATEGORIES:
        raise HTTPException(502, f"模型返回未知类别 {category!r}，原始输出：{content[:200]}")

    elements = obj.get("elements") or []
    if not isinstance(elements, list):
        elements = [str(elements)]
    elements = [str(x).strip() for x in elements if str(x).strip()][:10]

    usage = data.get("usage") or {}
    return {
        "category": category,
        "elements": elements,
        "reason": str(obj.get("reason", "")).strip()[:200],
        "model": data.get("model") or MODEL_NAME,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "request_id": uuid.uuid4().hex[:8],
    }


# ---------------------------------------------------------------- HTTPS 自签名证书

def ensure_cert(cert_dir: Path):
    """首次运行生成自签名证书（10 年），供手机端 HTTPS 摄像头使用。"""
    key_path, cert_path = cert_dir / "key.pem", cert_dir / "cert.pem"
    if key_path.exists() and cert_path.exists():
        return key_path, cert_path
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "corridor-risk.local")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_dir.mkdir(exist_ok=True)
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser(description="楼道消防风险识别后端")
    ap.add_argument("-HttpPort", type=int, default=8000)
    ap.add_argument("-HttpsPort", type=int, default=8443)
    ap.add_argument("-NoHttps", action="store_true")
    args = ap.parse_args()

    ip = lan_ip()
    http_port = args.HttpPort
    https_port = args.HttpsPort
    print("=" * 60)
    print("楼道消防风险识别 · 模型:", MODEL_NAME, "· 网关:", BASE_URL)
    if not API_KEY:
        print("!! 警告：未配置 DEEPSEEK_API_KEY，识别接口不可用")
    print(f"  本机访问(可拍照): http://localhost:{http_port}")
    print(f"  手机访问(上传):   http://{ip}:{http_port}")
    if not args.NoHttps:
        key_path, cert_path = ensure_cert(BASE_DIR / "certs")
        print(f"  手机访问(可拍照): https://{ip}:{https_port}")
        print("    自签名证书：浏览器提示不安全时点「高级 → 继续前往」即可。")
        print("    手机摄像头 getUserMedia 仅在 HTTPS 或 localhost 下可用。")
    print("=" * 60)

    configs = [uvicorn.Config(app, host="0.0.0.0", port=http_port, log_level="warning")]
    if not args.NoHttps:
        configs.append(uvicorn.Config(
            app, host="0.0.0.0", port=https_port, log_level="warning",
            ssl_certfile=str(cert_path), ssl_keyfile=str(key_path),
        ))
    servers = [uvicorn.Server(c) for c in configs]

    async def serve_all():
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(serve_all())


# API 路由先注册，静态文件兜底（放最后，避免覆盖 /api/*）
app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")

if __name__ == "__main__":
    main()
