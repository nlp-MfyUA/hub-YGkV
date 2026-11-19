"""Locate vulnerability/retest text blocks in parsed documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from pipeline.common.types import ParsedDocument, TextBlock

FOOTER_RE = re.compile(r"^第\s*\d+\s*页\s*共\s*\d+\s*页$")
PURE_PAGE_RE = re.compile(r"^\d+$")
PEN_TITLE_RE = re.compile(r"^\d+．\s*(?P<body>\S.*)$")
# Pattern A (5 batch-1 reports): "<system heading>" then "（N）<name>（severity）".
# A system heading is "N．..." that carries no severity suffix and does not
# introduce a bracketed item title.
PEN_SYSTEM_HEADING_RE = re.compile(
    r"^\d+．\s*(?!（\d+）)(?P<body>\S.*)$"
)
PEN_ANY_SEVERITY_SUFFIX_RE = re.compile(r"（(?:超危|严重|高危|中危|低危)）\s*$")
PEN_ITEM_TITLE_RE = re.compile(
    r"^（(?P<num>\d+)）\s*(?P<body>.+?)（(?:超危|严重|高危|中危|低危)）\s*$"
)
# Unbracketed field labels used by pattern A: "1 漏洞描述", "2 漏洞位置", ...
PEN_BARE_DESC_RE = re.compile(r"^\d+\s+漏洞描述$")
PEN_BARE_LABEL_RE = re.compile(r"^\d+\s+(?:漏洞描述|漏洞位置|测试过程|整改建议)\s*$")
REG_TITLE_RE = re.compile(r"^（(?P<num>[一二三四五六七八九十百]+)）\s*(?P<body>\S.*)$")
# Some 发改委 retest reports number items with arabic digits and drop the
# severity suffix: ``1．系统名`` + ``（1）越权访问`` + ``漏洞描述：...``.
RETEST_ARABIC_TITLE_RE = re.compile(r"^（(?P<num>\d+)）\s*(?P<body>\S.*)$")
PEN_DESC_RE = re.compile(r"^（1）\s*漏洞描述")
REG_DESC_RE = re.compile(r"^漏洞描述\s*[:：]?")
PEN_SECTION_RE = re.compile(r"^[一二三四五六七八九十]+、\s*渗透测试情况")
REG_SECTION_RE = re.compile(r"^[一二三四五六七八九十]+、\s*漏洞描述")
PEN_END_RE = re.compile(r"^[一二三四五六七八九十]+、\s*附录")
REG_END_RE = re.compile(r"^[一二三四五六七八九十]+、\s*回归测试人员")
REG_STATUS_SECTION_RE = re.compile(r"^[一二三四五六七八九十]+、\s*回归测试情况")
REG_STATUS_END_RE = re.compile(r"^[一二三四五六七八九十]+、\s*附录")
RETEST_DATE_RE = re.compile(r"^回归测试时间\s*[:：]\s*(?P<date>.+)$")
SEVERITY_SUFFIX_RE = re.compile(r"（(超危|严重|高危|中危|低危)）\s*$")
KV_FINDING_RE = re.compile(r"^Finding\s*#?\s*\d+", re.IGNORECASE)
KV_VULN_RE = re.compile(r"^Vulnerability\s*[:：]\s*(?P<vuln>.+)$", re.IGNORECASE)


@dataclass
class _IndexedLine:
    page: int
    text: str


def _clean(text: str) -> str:
    """Normalize whitespace in a line."""
    return " ".join(text.split())


def _is_toc_page(lines: Iterable[str]) -> bool:
    """Detect a table-of-contents page."""
    lines = list(lines)
    dot_leaders = sum("...." in line for line in lines)
    if dot_leaders >= 5:
        return True
    title_like = sum(
        bool(PEN_TITLE_RE.match(line) or REG_TITLE_RE.match(line)) for line in lines
    )
    has_description = any(
        PEN_DESC_RE.match(line) or REG_DESC_RE.match(line) for line in lines
    )
    return title_like >= 5 and not has_description


def _flatten(doc: ParsedDocument) -> list[_IndexedLine]:
    """Flatten page texts, removing footers/page numbers and TOC pages."""
    lines: list[_IndexedLine] = []
    for page in doc.text_blocks:
        cleaned = [
            _clean(line)
            for line in page.lines
            if _clean(line)
            and not FOOTER_RE.match(_clean(line))
            and not PURE_PAGE_RE.match(_clean(line))
        ]
        if _is_toc_page(cleaned):
            continue
        for line in cleaned:
            lines.append(_IndexedLine(page=page.page, text=line))
    return lines


def _section_start(
    lines: list[_IndexedLine],
    report_type: Literal["pentest", "retest"],
) -> Optional[int]:
    """Return the index of the vulnerability section start."""
    pattern = PEN_SECTION_RE if report_type == "pentest" else REG_SECTION_RE
    for index, line in enumerate(lines):
        if pattern.match(line.text):
            return index
    return None


def _section_end(lines: list[_IndexedLine], start: int, report_type: str) -> int:
    """Return the exclusive end index of the vulnerability section."""
    pattern = PEN_END_RE if report_type == "pentest" else REG_END_RE
    for index in range(start + 1, len(lines)):
        if pattern.match(lines[index].text):
            return index
    return len(lines)


def _is_system_heading(line: str) -> bool:
    """Return True for a pattern-A system heading such as ``1．上海市...子系统``."""
    if PEN_ANY_SEVERITY_SUFFIX_RE.search(line):
        return False
    return PEN_SYSTEM_HEADING_RE.match(line) is not None


def _pattern_a_title_at(
    lines: list[_IndexedLine], index: int
) -> Optional[tuple[str, list[str]]]:
    """Return the title parts for a pattern-A item title ``（1）越权访问（中危）``.

    The unbracketed label ``1 漏洞描述`` must follow within two lines; the
    parent system heading (``1．xxx``) is carried as context only.
    """
    match = PEN_ITEM_TITLE_RE.match(lines[index].text)
    if not match:
        return None
    parts = [lines[index].text]
    look = index + 1
    while look < len(lines) and look <= index + 2:
        next_line = lines[look].text
        if PEN_BARE_DESC_RE.match(next_line):
            return " ".join(parts), parts + [next_line]
        if PEN_ITEM_TITLE_RE.match(next_line) or _is_system_heading(next_line):
            return None
        if PEN_BARE_LABEL_RE.match(next_line):
            return None
        parts.append(next_line)
        look += 1
    return None


def _locate_pattern_a_blocks(
    body: list[_IndexedLine], retest_date: Optional[str] = None
) -> list[TextBlock]:
    """Fallback splitter for reports using ``（N）name（severity）`` + ``N 漏洞描述``."""
    accepted: list[tuple[int, str, list[str]]] = []
    index = 0
    while index < len(body):
        title = _pattern_a_title_at(body, index)
        if title is not None:
            raw_title, title_lines = title
            accepted.append((index, raw_title, title_lines))
            index += max(1, len(title_lines) - 1)
        index += 1

    blocks: list[TextBlock] = []
    for position, (start_index, raw_title, title_lines) in enumerate(accepted):
        next_index = (
            accepted[position + 1][0] if position + 1 < len(accepted) else len(body)
        )
        block_lines = title_lines + [
            line.text for line in body[start_index + len(title_lines) : next_index]
        ]
        title = SEVERITY_SUFFIX_RE.sub("", _strip_title(raw_title, "pentest"))
        title = re.sub(r"^（\d+）\s*", "", title).strip()
        blocks.append(
            TextBlock(
                report_type="pentest",
                raw_title=raw_title,
                title=title,
                page_start=body[start_index].page,
                page_end=body[max(next_index - 1, start_index)].page,
                lines=block_lines,
                retest_date=retest_date,
                format="pattern_a",
            )
        )
    return blocks


def _title_at(
    lines: list[_IndexedLine], index: int, report_type: str
) -> Optional[tuple[str, list[str]]]:
    """Return the merged title parts if a valid entry starts at *index*."""
    line = lines[index].text
    match = (
        PEN_TITLE_RE.match(line)
        if report_type == "pentest"
        else REG_TITLE_RE.match(line)
    )
    if not match and report_type == "retest":
        # Incremental fallback shape: ``（1）越权访问`` with an arabic digit and
        # no severity suffix. Only accepted when the next line is the field
        # label ``漏洞描述：``, so plain arabic list items cannot be mistaken
        # for vulnerability titles.
        match = RETEST_ARABIC_TITLE_RE.match(line)
        if match:
            if index + 1 >= len(lines):
                return None
            if not REG_DESC_RE.match(lines[index + 1].text):
                return None
    if not match:
        return None

    parts = [line]
    look = index + 1
    while look < len(lines) and look <= index + 2:
        next_line = lines[look].text
        if report_type == "pentest" and PEN_DESC_RE.match(next_line):
            return " ".join(parts), parts + [next_line]
        if report_type == "retest" and REG_DESC_RE.match(next_line):
            return " ".join(parts), parts + [next_line]
        if next_line.startswith("（") or PEN_TITLE_RE.match(next_line):
            return None
        parts.append(next_line)
        look += 1
    return None


def _strip_title(raw_title: str, report_type: str) -> str:
    """Remove the numbering and severity suffix from a title."""
    if report_type == "pentest":
        title = PEN_TITLE_RE.match(raw_title)
        text = title.group("body") if title else raw_title
    else:
        title = REG_TITLE_RE.match(raw_title) or RETEST_ARABIC_TITLE_RE.match(raw_title)
        text = title.group("body") if title else raw_title
    text = SEVERITY_SUFFIX_RE.sub("", text)
    return text.strip()


def _normalise_title(value: str) -> str:
    """Normalize a title for section 二/四 joining."""
    value = SEVERITY_SUFFIX_RE.sub("", value)
    value = re.sub(r"^（[一二三四五六七八九十百]+）\s*", "", value)
    value = re.sub(r"^（\d+）\s*", "", value)
    value = re.sub(r"^\d+．\s*", "", value)
    return re.sub(r"[^\w]+", "", value.lower())


def _retest_item_title(line: str) -> bool:
    """True for both ``（一）`` and the ``（1）`` fallback shape."""
    return bool(REG_TITLE_RE.match(line) or RETEST_ARABIC_TITLE_RE.match(line))


def _retest_status_map(
    lines: list[_IndexedLine],
) -> dict[str, tuple[str, int]]:
    """Collect section 四 retest status text/page by normalized title."""
    start = None
    for index, line in enumerate(lines):
        if REG_STATUS_SECTION_RE.match(line.text):
            start = index
            break
    if start is None:
        return {}
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if REG_STATUS_END_RE.match(lines[index].text):
            end = index
            break
    status_map: dict[str, tuple[str, int]] = {}
    current_title: Optional[str] = None
    current_lines: list[str] = []
    current_page: Optional[int] = None
    for line in lines[start + 1 : end]:
        if _retest_item_title(line.text):
            if current_title is not None and current_page is not None:
                status_map[current_title] = (
                    " ".join(current_lines),
                    current_page,
                )
            current_title = _normalise_title(line.text)
            current_lines = []
            current_page = line.page
        elif current_title is not None:
            current_lines.append(line.text)
    if current_title is not None and current_page is not None:
        status_map[current_title] = (" ".join(current_lines), current_page)
    return status_map


def _retest_date(lines: list[_IndexedLine]) -> Optional[str]:
    """Extract the retest date from section 三."""
    for line in lines:
        match = RETEST_DATE_RE.match(line.text)
        if match:
            return match.group("date").strip()
    return None


def _locate_kv_blocks(lines: list[_IndexedLine]) -> list[TextBlock]:
    """Fallback: split English KV blocks (Finding #N + Vulnerability:)."""
    starts = [
        index for index, line in enumerate(lines) if KV_FINDING_RE.match(line.text)
    ]
    blocks: list[TextBlock] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        segment = lines[start:end]
        vuln_line = next(
            (line for line in segment if KV_VULN_RE.match(line.text)), None
        )
        if vuln_line is None:
            continue
        match = KV_VULN_RE.match(vuln_line.text)
        if match is None:
            continue
        title = match.group("vuln").strip()
        blocks.append(
            TextBlock(
                report_type="pentest",
                raw_title=title,
                title=title,
                page_start=segment[0].page,
                page_end=segment[-1].page,
                lines=[line.text for line in segment],
                format="kv_block",
            )
        )
    return blocks


def locate_text_blocks(
    doc: ParsedDocument, report_type: Literal["pentest", "retest"]
) -> list[TextBlock]:
    """Split a parsed document into vulnerability/retest text blocks."""
    lines = _flatten(doc)
    start = _section_start(lines, report_type)
    if start is None:
        if report_type == "pentest":
            return _locate_kv_blocks(lines)
        return []
    end = _section_end(lines, start, report_type)
    body = lines[start + 1 : end]
    status_map = _retest_status_map(lines) if report_type == "retest" else {}
    retest_date = _retest_date(lines) if report_type == "retest" else None

    accepted: list[tuple[int, str, list[str]]] = []
    index = 0
    while index < len(body):
        title = _title_at(body, index, report_type)
        if title is not None:
            raw_title, title_lines = title
            accepted.append((index, raw_title, title_lines))
            index += max(1, len(title_lines) - 1)
        index += 1

    # Incremental fallback: only when the standard pentest template found no
    # entries do we try the pattern-A shape (system heading + （N）name（sev）).
    if not accepted and report_type == "pentest":
        pattern_a = _locate_pattern_a_blocks(body, retest_date)
        if pattern_a:
            return pattern_a

    blocks: list[TextBlock] = []
    for position, (start_index, raw_title, title_lines) in enumerate(accepted):
        next_index = (
            accepted[position + 1][0] if position + 1 < len(accepted) else len(body)
        )
        block_lines = title_lines + [
            line.text for line in body[start_index + len(title_lines) : next_index]
        ]
        title = _strip_title(raw_title, report_type)
        status_entry = status_map.get(_normalise_title(raw_title))
        status_text = status_entry[0] if status_entry else None
        status_page = status_entry[1] if status_entry else None
        blocks.append(
            TextBlock(
                report_type=report_type,
                raw_title=raw_title,
                title=title,
                page_start=body[start_index].page,
                page_end=body[max(next_index - 1, start_index)].page,
                lines=block_lines,
                status_text=status_text,
                retest_date=retest_date,
                status_page=status_page,
            )
        )
    if not blocks and report_type == "pentest":
        return _locate_kv_blocks(lines)
    return blocks
