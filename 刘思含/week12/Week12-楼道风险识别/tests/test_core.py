"""不依赖网络的单元测试：图片预处理 + 一致性校验。

运行: python -m pytest tests -q
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.analyzer import _check_consistency, _parse_boxes
from app.image_utils import ImageProcessError, load_image, preprocess
from app.schemas import HallwayRisk


def make_image(w: int, h: int, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 130, 140)).save(buf, format=fmt)
    return buf.getvalue()


def test_preprocess_resizes_large_image():
    raw = make_image(4000, 3000)
    out = preprocess(raw, max_edge=1280)
    img = Image.open(io.BytesIO(out))
    assert max(img.size) == 1280
    assert img.format == "JPEG"
    assert len(out) < len(raw)


def test_preprocess_keeps_small_image_size():
    raw = make_image(640, 480)
    img = Image.open(io.BytesIO(preprocess(raw)))
    assert img.size == (640, 480)


def test_bad_bytes_raise():
    with pytest.raises(ImageProcessError):
        load_image(b"not an image")


def _risk(**kw) -> HallwayRisk:
    base = dict(
        is_hallway=True,
        observations=["通道内有纸箱"],
        hazards=["纸箱"],
        risk_level="medium",
        risk_score=55,
        reason="堆物较多",
        advice=[],
    )
    base.update(kw)
    return HallwayRisk(**base)


def test_consistency_ok():
    _check_consistency(_risk())


def test_high_without_ev_keyword_rejected():
    with pytest.raises(ValueError):
        _check_consistency(_risk(risk_level="high", risk_score=80, hazards=["纸箱"]))


def test_high_with_ev_keyword_passes():
    _check_consistency(
        _risk(risk_level="high", risk_score=90, hazards=["电动自行车"])
    )


def test_non_hallway_conflict_rejected():
    with pytest.raises(ValueError):
        _check_consistency(
            _risk(is_hallway=True, risk_level="non_hallway", risk_score=0, hazards=[])
        )


def test_score_out_of_range_rejected():
    with pytest.raises(ValueError):
        _check_consistency(_risk(risk_level="none", risk_score=95, hazards=[]))


def test_parse_boxes_with_fence():
    text = '```json\n{"boxes": [[0.1,0.2,0.5,0.6]]}\n```'
    assert _parse_boxes(text) == [[0.1, 0.2, 0.5, 0.6]]


def test_parse_boxes_invalid_returns_empty():
    assert _parse_boxes('{"boxes": []}') == []
    assert _parse_boxes("没有框") == []
    assert _parse_boxes('{"boxes": [[0.5,0.5,0.1,0.1]]}') == []  # 反向框丢弃
