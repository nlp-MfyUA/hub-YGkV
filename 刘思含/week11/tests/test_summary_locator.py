"""Tests for the summary paragraph locator."""

from __future__ import annotations

from pipeline.phase2_parse.summary_locator import locate_summary


def test_standard_format() -> None:
    result = locate_summary(
        ["情况如下：超危漏洞 0 个，高危漏洞 2 个，中危漏洞3个，低危漏洞 0个。"]
    )
    assert result["declared_total"] == 5
    assert result["counts"]["高危"] == 2
    assert result["declares_zero"] is False


def test_severity_variant() -> None:
    result = locate_summary(
        ["情况如下：严重漏洞 0 个，高危漏洞 2 个，中危漏洞3个，低危漏洞 0个。"]
    )
    assert result["declared_total"] == 5
    assert result["counts"]["严重"] == 0


def test_line_break_variant() -> None:
    result = locate_summary(
        [
            "评估发现的漏洞\n情况如下：超危漏洞 0 个，高危漏洞 7 个，中危漏洞 9个，低危漏洞 3个。"
        ]
    )
    assert result["declared_total"] == 19


def test_spaced_variant() -> None:
    result = locate_summary(
        [
            "况 如 下 ： 超 危 漏 洞 0 个 ， 高 危 漏 洞 6 个 ， 中 危 漏 洞 7 个 ， 低 危 漏 洞 0 个 。"
        ]
    )
    assert result["declared_total"] == 13


def test_missing_space_variant() -> None:
    result = locate_summary(
        ["情况如下：超危漏洞 2 个，高危漏洞 27 个，中危漏洞12 个，低危漏洞 5个。"]
    )
    assert result["declared_total"] == 46


def test_zero_declaration_text() -> None:
    result = locate_summary(["本次渗透测试未发现明显安全漏洞。"])
    assert result["declared_total"] == 0
    assert result["declares_zero"] is True


def test_english_zero_declaration() -> None:
    result = locate_summary(["No vulnerability findings are included."])
    assert result["declared_total"] == 0
    assert result["declares_zero"] is True


def test_no_summary() -> None:
    result = locate_summary(["Scope Document", "No counts here."])
    assert result["declared_total"] is None
    assert result["declares_zero"] is False
