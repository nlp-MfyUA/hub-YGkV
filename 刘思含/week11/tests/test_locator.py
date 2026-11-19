"""Tests for the text block locator."""

from __future__ import annotations

from pipeline.common.types import PageText, ParsedDocument
from pipeline.phase2_parse.text_block_locator import locate_text_blocks

TOC = [
    "目录",
    "一、 测试概述............................................................................................................3",
    "二、 渗透测试情况.....................................................................................................8",
    "1． 鉴权绕过（高危）.....................................................................8",
    "（1） 漏洞描述..................................................................................8",
    "2． 账号密码泄露（高危）.....................................................................13",
    "（1） 漏洞描述..................................................................................13",
    "三、 附录：漏洞风险等级定义..................................................................................53",
]

PENTEST_BODY = [
    "二、渗透测试情况",
    "（一）渗透整体情况",
    "情况如下：超危漏洞 0 个，高危漏洞 2 个，中危漏洞 0 个，低危漏洞 0 个。",
    "（二）漏洞详情",
    "1．鉴权绕过（高危）",
    "（1）漏洞描述",
    "登录鉴权绕过漏洞是一种安全漏洞。",
    "（2）漏洞位置",
    "https://example.test/api/permission/graphql/",
    "（3）测试过程",
    "使用手机号登录，显示角色校验失败。",
    "（4）整改建议",
    "添加正确的身份验证和授权措施。",
    "1.完善鉴权措施，在用户每次访问或操作资源时进行严格的权限检查；",
    "2．应全面检查并对系统内的所有功能接口进行权限检查。",
    "2．账号密码泄露（高危）",
    "（1）漏洞描述",
    "系统存在弱密码泄露情况。",
    "（2）漏洞位置",
    "https://example.test/user/login",
    "（3）测试过程",
    "使用弱密码访问有效。",
    "（4）整改建议",
    "增加密码强度验证机制。",
]

RETEST_BODY = [
    "二、漏洞描述",
    "（一）逻辑漏洞-前端校验绕过",
    "漏洞描述：测试发现找回密码功能存在前端校验绕过。",
    "漏洞位置：https://example.test/account/forgetPhone",
    "（二）逻辑漏洞-文件上传绕过",
    "漏洞描述：测试发现文件上传功能存在前端校验绕过。",
    "漏洞位置：https://example.test/upload",
    "三、回归测试人员及时间",
    "回归测试时间：2026年2月-6月",
    "四、回归测试情况",
    "（一）逻辑漏洞-前端校验绕过",
    "经过复测，确认已更新逻辑，该漏洞已修复完成。",
    "（二）逻辑漏洞-文件上传绕过",
    "经过复测，确认已增加文件类型限制，该漏洞已修复完成。",
    "五、附录：漏洞风险等级定义",
]


def _doc(lines: list[str], page: int = 2) -> ParsedDocument:
    pages = [
        PageText(page=1, text="\n".join(TOC), lines=TOC),
        PageText(page=page, text="\n".join(lines), lines=lines),
    ]
    return ParsedDocument(source_file="synthetic.pdf", page_count=2, text_blocks=pages)


def test_toc_page_is_removed_and_pentest_entries_split() -> None:
    blocks = locate_text_blocks(_doc(PENTEST_BODY), "pentest")
    assert len(blocks) == 2
    assert blocks[0].title == "鉴权绕过"
    assert blocks[1].title == "账号密码泄露"
    assert "应全面检查" in "\n".join(blocks[0].lines)
    assert all("...." not in line for block in blocks for line in block.lines)


def test_pentest_section_suffix_variant_is_supported() -> None:
    body = ["二、渗透测试情况-安全系统"] + PENTEST_BODY[1:]
    blocks = locate_text_blocks(_doc(body), "pentest")
    assert len(blocks) == 2


def test_retest_entries_split_and_status_joined() -> None:
    blocks = locate_text_blocks(_doc(RETEST_BODY), "retest")
    assert len(blocks) == 2
    assert blocks[0].title == "逻辑漏洞-前端校验绕过"
    assert blocks[0].status_text is not None
    assert "已修复完成" in blocks[0].status_text
    assert blocks[0].retest_date == "2026年2月-6月"
    assert blocks[1].status_text is not None
