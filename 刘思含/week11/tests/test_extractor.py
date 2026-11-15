"""Tests for the field extractor."""

from __future__ import annotations

from pipeline.common.types import CanonicalVulnRecord, RetestRecord, TextBlock
from pipeline.phase2_parse.field_extractor import (
    assign_instance_index,
    extract_record,
)


def _pentest_block() -> TextBlock:
    lines = [
        "1．鉴权绕过（高危）",
        "（1）漏洞描述",
        "登录鉴权绕过漏洞是一种安全漏洞。",
        "（2）漏洞位置",
        "https://example.test/api/permission/graphql/",
        "（3）测试过程",
        "使用手机号登录，显示角色校验失败。",
        "（4）整改建议",
        "添加正确的身份验证和授权措施。",
    ]
    return TextBlock(
        report_type="pentest",
        raw_title="1．鉴权绕过（高危）",
        title="鉴权绕过",
        page_start=2,
        page_end=2,
        lines=lines,
    )


def test_pentest_extraction() -> None:
    record = extract_record(_pentest_block(), "report.pdf")
    assert isinstance(record, CanonicalVulnRecord)
    assert record.vuln_name == "鉴权绕过"
    assert record.severity_raw == "高危"
    assert record.extraction_method == "text_block"
    assert record.source_page == 2
    assert record.description_snippet == "登录鉴权绕过漏洞是一种安全漏洞。"


def test_retest_extraction_with_status() -> None:
    block = TextBlock(
        report_type="retest",
        raw_title="（一）逻辑漏洞-前端校验绕过",
        title="逻辑漏洞-前端校验绕过",
        page_start=5,
        page_end=5,
        lines=[
            "（一）逻辑漏洞-前端校验绕过",
            "漏洞描述：测试发现找回密码功能存在前端校验绕过。",
            "漏洞位置：https://example.test/account/forgetPhone",
        ],
        status_text="经过复测，确认已更新逻辑，该漏洞已修复完成。",
        retest_date="2026年2月-6月",
    )
    record = extract_record(block, "retest.pdf")
    assert isinstance(record, RetestRecord)
    assert record.raw_vuln_name == "逻辑漏洞-前端校验绕过"
    assert record.retest_status == "fixed"
    assert record.retest_status_raw
    assert record.retest_date == "2026年2月-6月"
    assert record.parent_vuln_name == record.raw_vuln_name
    assert record.match_confidence == "none"


def test_retest_label_own_line_variant() -> None:
    block = TextBlock(
        report_type="retest",
        raw_title="（二十）登录逻辑绕过",
        title="登录逻辑绕过",
        page_start=10,
        page_end=10,
        lines=[
            "（二十）登录逻辑绕过",
            "漏洞描述",
            "测试发现站点存在登录逻辑绕过。",
            "漏洞位置",
            "https://example.test/login",
        ],
        status_text="",
    )
    record = extract_record(block, "retest.pdf")
    assert isinstance(record, RetestRecord)
    assert record.retest_status == "unknown"
    assert record.retest_status_raw == ""
    assert record.evidence_snippet == "测试发现站点存在登录逻辑绕过。"


def test_kv_block_fallback() -> None:
    block = TextBlock(
        report_type="pentest",
        raw_title="SQL Injection",
        title="SQL Injection",
        page_start=1,
        page_end=1,
        lines=[
            "Finding #1",
            "Severity: High",
            "Vulnerability: SQL Injection",
            "CWE: CWE-89",
            "Location: https://test.example.com/api/login",
        ],
        format="kv_block",
    )
    record = extract_record(block, "no_table.pdf")
    assert isinstance(record, CanonicalVulnRecord)
    assert record.vuln_name == "SQL Injection"
    assert record.severity_raw == "High"
    assert record.extraction_method == "kv_block"
    assert record.cwe_id == "CWE-89"


def test_assign_instance_index_ignores_input_values() -> None:
    def build(index: int) -> CanonicalVulnRecord:
        return CanonicalVulnRecord(
            vuln_name="前端校验绕过",
            severity_raw="高危",
            source_file="x.pdf",
            source_page=1,
            instance_index=index,
            type_raw=None,
            cvss_score=None,
            component=None,
            cwe_id=None,
            description_snippet=None,
            extraction_method="text_block",
            confidence="high",
        )

    assigned = assign_instance_index([build(5), build(5)])
    assert [record.instance_index for record in assigned] == [1, 2]
