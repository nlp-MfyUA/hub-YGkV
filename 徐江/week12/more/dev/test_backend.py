"""离线测试：裁决器 / 解析容错 / 图片校验单元测试 + TestClient 全链路（stub provider）。

用法：python dev/test_backend.py
不访问真实模型 API；.env 需存在（lifespan 启动校验用），密钥有效性不影响本测试。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image

from backend import main as backend_main
from backend.arbiter import arbitrate
from backend.config import Settings
from backend.errors import (
    ImageTooLargeError,
    ImageTooSmallError,
    ModelOutputUnparseableError,
    UnsupportedImageTypeError,
)
from backend.providers.base import RawResult, VisionProvider
from backend.schemas import ModelOutput, Signal
from backend.utils import parse_model_json, validate_image

PASS = FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


# ---------------------------------------------------------------- 单元测试

def make_jpeg(size: int, color=(200, 30, 30)) -> bytes:
    img = Image.new("RGB", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def unit_arbiter() -> None:
    print("[单元] 裁决器")
    # 多信号取最高：自报低风险但含高风险信号 → 覆盖
    out = ModelOutput(scene_type="stairwell", risk_level="低风险", confidence="high",
                      signals=[Signal(type="堆物", level="低风险"),
                               Signal(type="电动车", level="高风险")])
    level, override = arbitrate(out)
    check("多信号取最高", level == "高风险" and override is True, f"got {level}/{override}")

    # 单信号一致 → 不覆盖
    out = ModelOutput(scene_type="corridor", risk_level="中风险", confidence="high",
                      signals=[Signal(type="纸箱", level="中风险")])
    level, override = arbitrate(out)
    check("单信号一致不覆盖", level == "中风险" and override is False)

    # signals 为空 → 信任自报
    out = ModelOutput(scene_type="corridor", risk_level="无风险", confidence="high")
    level, override = arbitrate(out)
    check("空信号信任自报", level == "无风险" and override is False)

    # non_corridor 短路：忽略 signals
    out = ModelOutput(scene_type="non_corridor", risk_level="非楼道", confidence="low",
                      signals=[Signal(type="电动车", level="高风险")])
    level, override = arbitrate(out)
    check("非楼道短路", level == "非楼道" and override is False)

    # 模型自报与裁决一致 → override False
    out = ModelOutput(scene_type="garage_passage", risk_level="高风险", confidence="high",
                      signals=[Signal(type="飞线充电", level="高风险")])
    level, override = arbitrate(out)
    check("裁决与自报一致", level == "高风险" and override is False)


def unit_parse_json() -> None:
    print("[单元] JSON 容错解析")
    check("围栏剥离", parse_model_json('```json\n{"a": 1}\n```') == {"a": 1})
    check("前后缀噪声", parse_model_json('好的，结果如下：\n{"a": 1}\n以上。') == {"a": 1})
    check("无围栏裸 JSON", parse_model_json('{"a": 1}') == {"a": 1})
    try:
        parse_model_json("完全没有 JSON")
        check("无 JSON 抛错", False)
    except ModelOutputUnparseableError:
        check("无 JSON 抛错", True)
    try:
        parse_model_json('{"a": 坏JSON}')
        check("坏 JSON 抛错", False)
    except ModelOutputUnparseableError:
        check("坏 JSON 抛错", True)
    try:
        parse_model_json("[1, 2, 3]")
        check("非对象抛错", False)
    except ModelOutputUnparseableError:
        check("非对象抛错", True)


def unit_validate_image() -> None:
    print("[单元] 图片校验")
    w, h = validate_image(make_jpeg(300), "image/jpeg")
    check("正常图片通过", (w, h) == (300, 300))
    try:
        validate_image(make_jpeg(100), "image/jpeg")
        check("尺寸过小抛错", False)
    except ImageTooSmallError:
        check("尺寸过小抛错", True)
    try:
        validate_image(make_jpeg(300), "image/gif")
        check("MIME 不支持抛错", False)
    except UnsupportedImageTypeError:
        check("MIME 不支持抛错", True)
    try:
        validate_image(b"not an image at all", "image/jpeg")
        check("非图片字节抛错", False)
    except UnsupportedImageTypeError:
        check("非图片字节抛错", True)
    try:
        validate_image(make_jpeg(300), "image/jpeg", max_mb=0)
        check("超过大小抛错", False)
    except ImageTooLargeError:
        check("超过大小抛错", True)
    w, h = validate_image(make_jpeg(300), None)  # content_type 缺失 → Pillow 兜底
    check("缺 content_type 嗅探兜底", (w, h) == (300, 300))


# ---------------------------------------------------------------- 全链路

class StubProvider(VisionProvider):
    """按脚本返回固定文本的 stub provider。"""

    name = "stub"
    model = "stub-model"

    def __init__(self, text: str):
        self._text = text

    async def analyze(self, image_b64: str, system_prompt: str, user_text: str,
                      *, mime: str = "image/jpeg") -> RawResult:
        return RawResult(text=self._text, latency_ms=123, provider=self.name, model=self.model)


def integration() -> None:
    print("[集成] TestClient 全链路（stub provider）")
    from fastapi.testclient import TestClient

    ok_payload = {
        "scene_type": "stairwell", "risk_level": "低风险", "confidence": "high",
        "evidence": "测试证据",
        "signals": [{"type": "电动车", "level": "高风险", "detail": "stub"}],
    }
    override_payload = dict(ok_payload)  # 自报低风险 + 高风险信号 → 服务端覆盖
    agree_payload = {
        "scene_type": "corridor", "risk_level": "中风险", "confidence": "medium",
        "evidence": "一致用例",
        "signals": [{"type": "纸箱", "level": "中风险", "detail": "stub"}],
    }

    with TestClient(backend_main.app) as client:
        backend_main.app.state.provider = StubProvider(json.dumps(ok_payload, ensure_ascii=False))

        # 1) 成功 + 服务端覆盖
        resp = client.post("/api/analyze",
                           files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")})
        body = resp.json()
        check("analyze 200", resp.status_code == 200, f"got {resp.status_code} {body}")
        check("arbiter_override 覆盖为高风险",
              body.get("risk_level") == "高风险" and body.get("arbiter_override") is True)
        check("signals 透传", len(body.get("signals", [])) == 1)
        check("latency/provider/model", body.get("provider") == "stub"
              and body.get("model") == "stub-model" and body.get("latency_ms", -1) >= 0)

        # 2) 一致用例不覆盖
        backend_main.app.state.provider = StubProvider(json.dumps(agree_payload, ensure_ascii=False))
        resp = client.post("/api/analyze",
                           files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")})
        body = resp.json()
        check("一致用例 override=false",
              body.get("arbiter_override") is False and body.get("risk_level") == "中风险")

        # 3) 错误矩阵
        backend_main.app.state.provider = StubProvider("完全不是 JSON")
        resp = client.post("/api/analyze",
                           files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")})
        check("输出非 JSON → 502 model_output_unparseable",
              resp.status_code == 502 and resp.json().get("error_code") == "model_output_unparseable",
              str(resp.json()))

        backend_main.app.state.provider = StubProvider(json.dumps(
            {"scene_type": "stairwell", "risk_level": "特高风险", "confidence": "high",
             "evidence": "x"}, ensure_ascii=False))
        resp = client.post("/api/analyze",
                           files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")})
        check("枚举越界 → 502 invalid_enum",
              resp.status_code == 502 and resp.json().get("error_code") == "invalid_enum",
              str(resp.json()))

        backend_main.app.state.provider = StubProvider(json.dumps(
            {"scene_type": "stairwell"}, ensure_ascii=False))
        resp = client.post("/api/analyze",
                           files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")})
        check("缺字段 → 502 model_output_unparseable",
              resp.status_code == 502 and resp.json().get("error_code") == "model_output_unparseable",
              str(resp.json()))

        resp = client.post("/api/analyze",
                           files={"image": ("t.jpg", make_jpeg(100), "image/jpeg")})
        check("尺寸过小 → 422 image_too_small",
              resp.status_code == 422 and resp.json().get("error_code") == "image_too_small")

        resp = client.post("/api/analyze",
                           files={"image": ("t.gif", b"GIF89a...", "image/gif")})
        check("格式不支持 → 422 unsupported_image_type",
              resp.status_code == 422 and resp.json().get("error_code") == "unsupported_image_type")

        # 大小上限：临时把配置改成 0 MB
        orig = backend_main.get_settings
        backend_main.get_settings = lambda: Settings(max_image_mb=0)
        try:
            resp = client.post("/api/analyze",
                               files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")})
            check("超过大小 → 413 image_too_large",
                  resp.status_code == 413 and resp.json().get("error_code") == "image_too_large")
        finally:
            backend_main.get_settings = orig

        # 演示令牌
        backend_main.get_settings = lambda: Settings(demo_token="secret")
        try:
            resp = client.post("/api/analyze",
                               files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")})
            check("缺令牌 → 401 unauthorized",
                  resp.status_code == 401 and resp.json().get("error_code") == "unauthorized")
            backend_main.app.state.provider = StubProvider(json.dumps(agree_payload, ensure_ascii=False))
            resp = client.post("/api/analyze",
                               files={"image": ("t.jpg", make_jpeg(300), "image/jpeg")},
                               headers={"X-Demo-Token": "secret"})
            check("带令牌 → 200", resp.status_code == 200)
        finally:
            backend_main.get_settings = orig

        # 4) health / config / 静态
        resp = client.get("/api/health")
        hb = resp.json()
        check("health 200 且含通道字段",
              resp.status_code == 200 and {"provider", "model", "api_key_configured"} <= set(hb))
        resp = client.get("/api/config")
        cb = resp.json()
        check("config 200 且不含密钥",
              resp.status_code == 200 and "key" not in json.dumps(cb).lower())
        resp = client.get("/")
        check("静态首页 200", resp.status_code == 200 and "楼道消防风险识别" in resp.text)
        resp = client.get("/app.js")
        check("静态 app.js 200", resp.status_code == 200)


def main() -> None:
    unit_arbiter()
    unit_parse_json()
    unit_validate_image()
    integration()
    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
