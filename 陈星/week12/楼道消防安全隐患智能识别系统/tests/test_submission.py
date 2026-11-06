"""运行：python -m pytest -q"""
import base64
import io
import itertools
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import main, risk, vision
from backend.imaging import MAX_FILE_BYTES, to_jpeg

client = TestClient(main.app)


def make_image(fmt="PNG", mode="RGB", size=(160, 110)):
    buffer = io.BytesIO()
    Image.new(mode, size, (200, 160, 120) if mode=="RGB" else (200, 160, 120, 100)).save(buffer, format=fmt)
    return buffer.getvalue()


def facts(**kwargs):
    data = dict.fromkeys(risk.REQUIRED_FLAGS, False)
    data.update(is_corridor=True, description="楼道照片", evidence=["可见现场物品"])
    data.update(kwargs)
    return data


def upload(raw, name="photo.png", provider="deepseek"):
    return client.post(
        "/api/analyze",
        data={"provider": provider},
        files={"image": (name, raw, "image/png")},
    )


def test_homepage_and_status_do_not_leak_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "SECRET_FOR_TEST")
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    status = client.get("/api/status")
    assert status.status_code == 200
    assert "SECRET_FOR_TEST" not in status.text
    assert status.json()["models"][0]["configured"] is True


def test_all_64_risk_combinations():
    for bits in itertools.product((False, True), repeat=len(risk.REQUIRED_FLAGS)):
        data = dict(zip(risk.REQUIRED_FLAGS, bits))
        expected = (
            "非楼道" if not data["is_corridor"] else
            "高风险" if data["electric_vehicle_or_battery"] or data["unsafe_charging"] else
            "中等风险" if data["severe_obstruction"] or data["large_combustible_pile"] else
            "低风险" if data["small_clutter"] else "无隐患"
        )
        assert risk.classify(data) == expected


def test_one_result_each_category():
    examples = [
        (facts(is_corridor=False), "非楼道"),
        (facts(), "无隐患"),
        (facts(small_clutter=True), "低风险"),
        (facts(large_combustible_pile=True), "中等风险"),
        (facts(electric_vehicle_or_battery=True), "高风险"),
    ]
    for item, expected in examples:
        parsed = risk.validate_facts(json.dumps(item, ensure_ascii=False))
        assert risk.classify(parsed) == expected


@pytest.mark.parametrize("raw", [
    "not json", "null", "[]", "{}", 
    json.dumps(facts(unsafe_charging="true"),ensure_ascii=False),
    json.dumps(facts(description=42),ensure_ascii=False),
    json.dumps(facts(evidence="纸箱"),ensure_ascii=False),
    json.dumps(facts(evidence=[3]),ensure_ascii=False),
])
def test_bad_model_output(raw):
    with pytest.raises(ValueError):
        risk.validate_facts(raw)


def test_image_normalization():
    for fmt in ("JPEG", "PNG", "WEBP"):
        processed = to_jpeg(make_image(fmt))
        with Image.open(io.BytesIO(processed)) as picture:
            assert picture.format == "JPEG"
            assert picture.size == (160, 110)
    transparent = to_jpeg(make_image("PNG", mode="RGBA"))
    assert Image.open(io.BytesIO(transparent)).mode == "RGB"


@pytest.mark.parametrize(("raw", "expected"), [
    (b"", 400),
    (b"not-an-image", 400),
    (b"x" * (MAX_FILE_BYTES + 1), 413),
    (make_image("GIF"), 400),
])
def test_invalid_images(raw, expected):
    assert upload(raw).status_code == expected


def test_no_api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    result = upload(make_image())
    assert result.status_code == 502
    assert "API Key" in result.json()["detail"]


@pytest.mark.parametrize(("provider", "hostname", "model"), [
    ("deepseek", "api.deepseek.com", "deepseek-flash"),
    ("qwen", "dashscope.aliyuncs.com", "qwen3-vl-flash"),
])
def test_realistic_http_payload_without_network(monkeypatch, provider, hostname, model):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "TEST_ONLY")
    monkeypatch.setenv("QWEN_API_KEY", "TEST_ONLY")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("QWEN_MODEL", "qwen3-vl-flash")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    model_facts = facts(electric_vehicle_or_battery=True,
                        large_combustible_pile=True,
                        evidence=["电动车", "大量纸箱"],
                        description="楼道停放电动车并堆积大量纸箱")

    def handle(request: httpx.Request):
        assert request.url.host == hostname
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer TEST_ONLY"
        payload = json.loads(request.content)
        assert payload["model"] == model
        assert payload["response_format"] == {"type": "json_object"}
        if provider == "deepseek":
            assert payload["thinking"] == {"type": "disabled"}
        else:
            assert payload["enable_thinking"] is False
        blocks = payload["messages"][0]["content"]
        assert blocks[0]["type"] == "text" and "JSON" in blocks[0]["text"]
        data_uri = blocks[1]["image_url"]["url"]
        assert data_uri.startswith("data:image/jpeg;base64,")
        assert base64.b64decode(data_uri.split(",",1)[1]).startswith(bytes([255, 216]))
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(model_facts, ensure_ascii=False)}}]
        })

    original = httpx.AsyncClient
    monkeypatch.setattr(vision.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    response = upload(make_image(), provider=provider)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["risk_level"] == "高风险"
    assert result["model"] == model
    assert result["provider"] == provider
    assert result["is_demo"] is False
    assert len(result["evidence"]) == 2


def test_model_returns_bad_json(monkeypatch):
    async def mock_inspect(_jpeg, _provider):
        return "not a valid json", "deepseek-flash"
    monkeypatch.setattr(main, "inspect_image", mock_inspect)
    result = upload(make_image())
    assert result.status_code == 502
    assert "JSON" in result.json()["detail"]


def test_unknown_provider():
    response = upload(make_image(), provider="unknown")
    assert response.status_code == 422
