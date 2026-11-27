#!/usr/bin/env python3
"""Build a search plan, then turn opened announcements into audited ESG cards."""

import argparse
import json
import re
import unicodedata
from calendar import monthrange
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


AUTHORITY = {
    "gov.cn", "cninfo.com.cn", "sse.com.cn", "hkexnews.hk", "ifrs.org",
    "globalreporting.org", "spglobal.com", "msci.com", "sustainalytics.com",
    "chng.com.cn", "ceic.com", "chinacoal.com", "crrcgc.cc", "bidding.csg.cn",
    "sz-water.com.cn", "szyd11.com", "ebidding.cecep.cn", "etp.dfmc.com.cn",
    "bgt.mof.gov.cn", "ccgp-shaanxi.gov.cn",
}
DATE = r"(20\d{2})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})(?:日|\b)"
PUBLISHED = re.compile(
    r"(?:发布(?:日期|时间|于)|公告(?:日期|时间)|信息时间|来源)\s*[:：|]?\s*"
    + DATE
)
MONEY = r"((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.\d{1,8})?)\s*(万元|元)?"
AWARD = r"(?:中标|成交)(?:\s*[(（]成交[)）])?\s*(?:价(?:格)?|结果(?:公示|公告)?|公告|金额)|采购结果(?:公示|公告)|中选公告|结果公告"
TENDER_TOPIC = r"esg|可持续发展|双碳|碳(?:达峰|中和|排放|足迹|核查|数据.{0,5}核查|交易|盘查|预算|减排|管理|基数|汇)|温室气体|能碳|减污降碳"
TOPICS = (
    ("气候披露", r"气候.{0,12}(?:披露|准则)|可持续.{0,8}(?:披露|电子化)|ISSB"),
    ("煤电与新能源", r"煤电.{0,12}新能源|灵活性改造|绿电|全容量并网"),
    ("碳市场与核算", r"配额|碳排放|全国碳市场|碳核查|碳预算"),
    ("绿色矿山", r"矿山|露天矿|矿卡|生态修复"),
    ("公司运营与资本变动", r"主要运营数据|季度报告|股权收购|并入资产|发电量"),
    ("ESG评级与治理", r"评级|评分|企业管治|S&P Global"),
    ("产品碳足迹", r"碳足迹|生命周期评价"),
    ("ESG报告与鉴证", r"ESG.{0,10}报告|可持续发展报告|鉴证"),
)
MONTHLY_FACTS = {
    "征求意见": r"(?:征求意见稿|征求意见|拟定)",
    "推荐性标准": r"推荐性标准",
    "正式公告": r"自(?:公布|发布)之日起施行",
    "并网": r"全容量并网",
    "初步决定": r"tentatively decided|初步决定",
    "口径调整": r"重述|追溯调整",
}
CN_DIGITS = dict(zip("零壹贰叁肆伍陆柒捌玖", range(10)))
CN_UNITS = {"拾": 10, "佰": 100, "仟": 1000, "万": 10**4, "亿": 10**8}


def normalized(value):
    return unicodedata.normalize("NFKC", value)


def dates(text):
    for match in re.finditer(DATE, text):
        try:
            yield date(*map(int, match.groups()))
        except ValueError:
            continue


def publication(text, url):
    lines = text.splitlines()
    for line in lines:
        if line.lstrip().startswith("【") and "〗" not in line:
            continue
        match = PUBLISHED.search(line.replace("]", ""))
        if match:
            found = next(dates(match[0]), None)
            if found:
                return found, "正文发布字段"
    for line in lines:
        value = line.strip().lstrip("#〖【 ").strip()
        if re.match(DATE + r"\s*(?:\d{1,2}:\d{2}(?::\d{2})?\s*)?来源", value):
            found = next(dates(value), None)
            if found:
                return found, "正文日期与来源"
    host = urlsplit(url).hostname or ""
    if host == "static.cninfo.com.cn":
        path = urlsplit(url).path
        match = re.match(r"/finalpage/(20\d{2}-\d{2}-\d{2})/\d+\.PDF$", path, re.I)
        if match:
            return date.fromisoformat(match[1]), "巨潮披露路径"
    return None, None


def canonical(url):
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"} or not parts.hostname
        or parts.username or parts.password
    ):
        raise ValueError("公告 URL 需要公开 HTTP(S) 地址")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", urlencode(sorted(query)), ""))


def authority(url, extra_domains):
    host = urlsplit(url).hostname or ""
    return any(host == domain or host.endswith("." + domain) for domain in AUTHORITY | extra_domains)


def quarterly(start, end):
    cursor = start
    while cursor <= end:
        month = ((cursor.month + 2) // 3) * 3
        quarter_end = min(end, date(cursor.year, month, monthrange(cursor.year, month)[1]))
        yield cursor, quarter_end
        cursor = quarter_end + timedelta(days=1)


def make_plan(args):
    if args.profile == "monthly":
        company = args.company
        pairs = [
            ("政策", f"{args.industry} 低碳 排放 煤电 政策 生态环境部 能源局"),
            ("评级", f"{company} {args.ticker} ESG 评级 MSCI 标普 变动"),
            ("标准", "可持续披露 气候 准则 标准 财政部 证监会 ISSB"),
            ("行业", f"{args.industry} 绿色转型 安全 新能源 行业 动态"),
            ("公司", f"{company} {args.ticker} 公告 运营 ESG site:cninfo.com.cn"),
            ("对标", f"{args.peers} {args.industry} 绿色 低碳 应用 案例"),
        ]
        periods = [(args.start, args.end)]
    else:
        stage = "中标 成交 采购结果" if args.mode == "awards" else "招标 询比 磋商 更正"
        pairs = [
            ("报告与鉴证", f"ESG 可持续发展报告 编制 鉴证 {stage}"),
            ("核算与核查", f"碳排放 核算 核查 {stage} site:gov.cn"),
            ("足迹与双碳", f"碳足迹 双碳 碳达峰 {stage}"),
            ("平台与咨询", f"能碳管理 碳减排 咨询 {stage} 公共资源"),
        ]
        periods = list(quarterly(args.start, args.end))
    queries = []
    for start, end in periods:
        lower, upper = start - timedelta(days=1), end + timedelta(days=1)
        for lane, query in pairs:
            date_terms = f"{start.year}年{start.month}月" if (start.year, start.month) == (end.year, end.month) else f"{start.year}年"
            queries.append({"lane": lane, "query": f"{query} {date_terms} after:{lower} before:{upper}"})
    queries.extend({"lane": "补查", "query": query} for query in getattr(args, "query", []))
    return {"profile": args.profile, "mode": args.mode, "queries": queries, "max_open": args.max_open}


def classify_award(title):
    if re.search(r"候选|预中标|废标|取消|终止|采购意向|征集|合同公告", title):
        return "excluded"
    if re.search(AWARD, title):
        return "award"
    if re.search(r"招标公告|询比|磋商公告|采购公告|谈判公告", title):
        return "opportunity"
    return "unknown"


def money(number, unit):
    value = Decimal(number.replace(",", "")) * (10_000 if unit == "万元" else 1)
    return value.quantize(Decimal("0.01")) if value > 0 and value == value.quantize(Decimal("0.01")) else None


def chinese_money(label):
    """Read uppercase whole RMB; decimals and unfamiliar notation require review."""
    value = label.replace("圆", "元").removesuffix("整").removesuffix("正")
    if not re.fullmatch(r"[零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+元", value):
        return None
    total, section, digit = 0, 0, 0
    for char in value[:-1]:
        if char in CN_DIGITS:
            digit = CN_DIGITS[char]
        elif char in "万亿":
            if char == "亿" and total:
                return None
            total += (section + digit) * CN_UNITS[char]
            section, digit = 0, 0
        else:
            if not digit:
                return None
            section += digit * CN_UNITS[char]
            digit = 0
    return Decimal(total + section + digit) if total + section + digit else None


def package_amounts(lines):
    """Read one explicit amount per numbered result package before service details."""
    in_results = False
    expected = set()
    amounts = {}
    table_index = None
    current = None
    reached_next_section = False
    for raw in lines:
        line = raw.strip().lstrip("# ")
        if not in_results:
            in_results = bool(re.match(r"(?:[三四]、)?(?:中标(?:\s*\(成交\))?信息|采购结果)(?:[:：]|$)", line))
            continue
        if re.match(r"[四五六]、\s*(?:主要标的|评审|代理|服务)", line):
            reached_next_section = True
            break
        package = re.match(r"(?:采购包|合同包)\s*(\d+)(?:\s*$|\s*[(（:：])", line)
        if package:
            current = int(package[1])
            expected.add(current)
            table_index = None
            continue
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        headings = [i for i, cell in enumerate(cells) if re.search(r"(?:中标|成交).*金额", cell)]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
            continue
        if headings:
            table_index = headings[0]
            continue
        if current is None or table_index is None or table_index >= len(cells):
            continue
        candidate = re.fullmatch(MONEY, cells[table_index])
        if not candidate or not candidate[2] or current in amounts:
            return None
        amount = money(*candidate.groups())
        if amount is None:
            return None
        amounts[current] = amount
    if reached_next_section and expected and set(amounts) == expected == set(range(1, max(expected) + 1)):
        return amounts
    return None


def award_amount(body, allow_packages=True):
    first = re.split(r"\n\s*(?:#+\s*)?[五六七]、\s*(?:评审专家|代理费|公告期限)", body, 1)[0]
    totals = re.findall(r"总(?:中标|成交)(?:\(成交\))?金额\s*[:：|]?\s*[￥¥]?\s*" + MONEY, first)
    candidates = {money(number, unit) for number, unit in totals if unit}
    candidates.discard(None)
    if len(candidates) == 1:
        return candidates.pop(), "公告项目总额"
    if len(candidates) > 1:
        return None, "多个冲突的公告总额"
    fields = re.findall(
        r"(?:中标(?:\(成交\))?|成交|中选)\s*(?:价(?:格)?|金额)\s*[:：]\s*(?:[￥¥]|RMB)?\s*"
        + MONEY,
        first,
        flags=re.I,
    )
    fixed = {money(number, unit) for number, unit in fields if unit}
    uppercase = re.findall(
        r"(?:中标|成交|中选)\s*价(?:格)?\s*[:：]\s*([零壹贰叁肆伍陆柒捌玖拾佰仟万亿元圆整正]+)",
        first,
    )
    fixed.update(chinese_money(item) for item in uppercase)
    if re.search(r"成交价(?:格)?\s*[:：][^\n]*[;；]\s*RMB\s*[\d,]+", first, re.I):
        for number in re.findall(r"\bRMB\s*([\d,]+(?:\.\d{1,2})?)", first, re.I):
            fixed.add(money(number, "元"))
    fixed.discard(None)
    if len(fixed) == 1:
        return fixed.pop(), "明确成交价字段"
    if len(fixed) > 1:
        return None, "多个冲突的成交价字段"
    grouped = package_amounts(first.splitlines()) if allow_packages else None
    if grouped:
        return sum(grouped.values(), Decimal(0)), f"结果表 {len(grouped)} 个标包合计"
    result = re.search(r"(?:成交|中标).{0,3}金额\s*\n([^\n]+)", first)
    if result and re.search(r"(?<!\d)\d[\d,]*(?:\.\d{1,2})?\s*元\s*$", result[1]):
        amount = re.search(MONEY + r"\s*$", result[1])
        if amount and amount[2]:
            return money(*amount.groups()), "成交表固定金额"
    return None, "未识别到唯一固定总额"


def project_number(body):
    match = re.search(r"(?:项目编号|项目编码|采购编号)\s*[:：]\s*([\w.〔〕﹝﹞-]+)", body)
    return match[1] if match else None


def detail(card, body):
    title = card["title"]
    card["topics"] = [label for label, pattern in TOPICS
                      if re.search(pattern, title, re.I) or re.search(pattern, body[:2400], re.I)]
    fact_body = body[:3500]
    card["signals"] = [label for label, pattern in MONTHLY_FACTS.items()
                       if re.search(pattern, title + "\n" + fact_body, re.I)]


def monthly_facts(text, title):
    facts = []
    if "主要运营数据公告" in title:
        for label in ("商品煤产量", "总发电量"):
            match = re.search(label + r"\s*[| ]*\s*(百万吨|十亿千瓦时)\s*[| ]*\s*([0-9]+(?:\.[0-9]+)?)", text)
            if match:
                facts.append(f"{label} {match[2]} {match[1]}（公告表首个期间）")
    matches = (
        (r"全国绿电交易[^。\n]{0,55}?交易电量达到([0-9,]+)亿千瓦时[^。\n]{0,12}?同比增长([0-9.]+)%", "全国绿电交易 {0} 亿千瓦时，同比增长 {1}%"),
        (r"鼓励融合项目年度碳排放水平较融合前降低([0-9.]+)%以上，\s*力争降低([0-9.]+)%以上", "所列融合场景的年度减排鼓励目标为至少 {0}%，力争至少 {1}%"),
        (r"其他\s*(\d+)\s*家标的公司纳入本公司财务报表合并范围", "报告披露纳入合并范围的标的公司 {0} 家"),
    )
    for pattern, template in matches:
        match = re.search(pattern.replace("，", ","), text)
        if match:
            facts.append(template.format(*match.groups()))
    return facts


def analyze(packet, args):
    cards, seen, seen_projects = [], set(), {}
    extra_domains = set(args.trusted_domain)
    for doc in packet["documents"]:
        source_url = canonical(doc["url"])
        body = normalized(doc["text"])
        title = normalized(doc["title"]).strip()
        day, date_source = publication(body, source_url) if body else (None, None)
        official = authority(source_url, extra_domains)
        card = {
            "id": doc["id"], "title": title, "url": doc["url"],
            "published": day.isoformat() if day else None, "date_source": date_source,
            "lane": doc.get("lane"), "ref": doc.get("ref"),
            "amount_yuan": None,
        }
        cards.append(card)
        stage = classify_award(title) if args.profile == "tender" else None
        relevant = bool(re.search(TENDER_TOPIC, title, re.I)) if stage else True
        expected_stage = "award" if args.mode == "awards" else "opportunity"
        issuer = re.search(r"(?:证券代码|股票代码)\s*[:：]?\s*(\d{6})", title + "\n" + body[:1800])
        different_issuer = (
            args.profile == "monthly" and args.ticker and issuer
            and urlsplit(source_url).hostname == "static.cninfo.com.cn" and issuer[1] != args.ticker
        )
        if source_url in seen:
            status, reason = "duplicate", "同一原文 URL"
        elif different_issuer:
            status, reason = "not_in_scope", "公告证券代码和目标公司不一致"
        elif args.profile == "tender" and (not relevant or stage in {"excluded", "award", "opportunity"}
                                          and stage != expected_stage):
            status, reason = "not_in_scope", "主题或公告阶段不符"
        elif doc["outcome"] != "opened" or not body.strip():
            status, reason = "review", "原文正文未取得"
        elif day and not args.start <= day <= args.end:
            status, reason = "out_of_window", "发布日超出观察期"
        elif not official:
            status, reason = "review", "发布者需核验"
        elif not day:
            status, reason = "review", "缺少可核实的发布日期"
        elif args.profile == "tender" and stage != expected_stage:
            status, reason = "review", "需核对正式结果或招标类型"
        elif args.profile == "tender" and args.mode == "live":
            status, reason = "review", "需打开最新更正，核对报名及投标截止"
        else:
            status, reason = "included", "发布期与证据门槛通过"
        if doc["outcome"] == "opened" and body.strip():
            seen.add(source_url)
        detail(card, body)
        if args.profile == "monthly" and status == "included":
            card["facts"] = monthly_facts(body, title)
        if status == "included" and stage == "award":
            number = project_number(body)
            amount, basis = award_amount(body, allow_packages=not doc.get("gap", False))
            card.update(project_number=number, amount_basis=basis,
                        amount_yuan=str(amount) if amount is not None else None)
            if number and number in seen_projects:
                first = seen_projects[number]
                if day == date.fromisoformat(first["published"]) and card["amount_yuan"] == first["amount_yuan"]:
                    status, reason = "duplicate", "同项目编号、日期及金额，需核对分包"
                else:
                    status, reason = "review", "同项目出现不同结果，需人工对照"
                    first.update(status=status, reason=reason, amount_yuan=None)
                card["amount_yuan"] = None
            elif number:
                seen_projects[number] = card
        card.update(status=status, reason=reason)
    included = [card for card in cards if card["status"] == "included"]
    priced = [Decimal(card["amount_yuan"]) for card in included if card["amount_yuan"] is not None]
    return {
        "profile": args.profile, "mode": args.mode,
        "window": [args.start.isoformat(), args.end.isoformat()],
        "counts": dict(sorted(Counter(card["status"] for card in cards).items())),
        "query_count": len(packet.get("queries", [])),
        "query_failures": packet.get("errors", []),
        "priced": len(priced), "amount_total_yuan": str(sum(priced, Decimal(0))) if priced else None,
        "cards": cards,
    }


def markdown(result):
    labels = {"included": "纳入", "out_of_window": "跨期", "duplicate": "重复",
              "not_in_scope": "排除", "review": "待核"}
    lines = [f"# ESG 证据摘要", "", f"观察期 {result['window'][0]} 至 {result['window'][1]}",
             "", "处理结果 " + "，".join(f"{labels[key]} {value} 条" for key, value in result["counts"].items())]
    if result["amount_total_yuan"] is not None:
        lines.extend(["", f"有唯一可计金额 {result['priced']} 条，合计 {result['amount_total_yuan']} 元。"])
    for card in result["cards"]:
        title = card["title"].replace("[", "（").replace("]", "）").replace("\n", " ")
        tags = "、".join(card["topics"] + card["signals"])
        facts = "。".join(card.get("facts", []))
        detail_text = f"。{tags}" if tags else ""
        if facts:
            detail_text += f"。{facts}"
        if card["amount_yuan"]:
            detail_text += f"。{card['amount_yuan']} 元（{card['amount_basis']}）"
        lines.append(f"- {card['id']} {labels[card['status']]}｜"
                     f"{card['published'] or '日期待核'}｜{card['reason']}{detail_text}。"
                     f"[{title}]({card['url']})")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("plan", "analyze"):
        parser = sub.add_parser(command)
        parser.add_argument("--profile", choices=("monthly", "tender"), required=True)
        parser.add_argument("--mode", choices=("awards", "live"), default="awards")
        parser.add_argument("--start", type=date.fromisoformat, required=True)
        parser.add_argument("--end", type=date.fromisoformat, required=True)
        parser.add_argument("--ticker", default="601088")
        if command == "plan":
            parser.add_argument("--company", default="中国神华")
            parser.add_argument("--industry", default="煤炭 煤电")
            parser.add_argument("--peers", default="中国中煤 中国华能 陕煤集团")
            parser.add_argument("--max-open", type=int, choices=range(1, 51), default=24)
            parser.add_argument("--query", action="append", default=[])
        else:
            parser.add_argument("packet", type=Path)
            parser.add_argument("--trusted-domain", action="append", default=[])
            parser.add_argument("--markdown", type=Path)
    args = p.parse_args()
    if args.start > args.end:
        p.error("--start must not follow --end")
    if args.profile == "monthly" and args.mode != "awards":
        p.error("--mode live applies to the tender profile")
    if args.command == "plan":
        output = make_plan(args)
    else:
        output = analyze(json.loads(args.packet.read_text(encoding="utf-8")), args)
        if args.markdown:
            args.markdown.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
