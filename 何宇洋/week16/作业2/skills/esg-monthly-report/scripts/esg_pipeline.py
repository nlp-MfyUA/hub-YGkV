"""ESG helpers. Python 3.10+, standard library only; no paid API required.

search: Bing RSS discovery + bounded HTML fetch + extractive summary (not verification).
analyze: conservative record normalization, audit and exact CNY statistics.
monitor: local outbox, version-aware deduplication, explicit acknowledgement.
"""
import argparse
import hashlib
import html
import json
import re
import statistics
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(p)


def day(s):
    return date.fromisoformat(s)


def window(as_of):
    d = day(as_of)
    start = d.replace(day=1) - timedelta(days=1)
    try:
        year_start = d.replace(year=d.year - 2)
    except ValueError:
        year_start = d.replace(year=d.year - 2, day=28)
    return {'monthly_start': start.replace(day=1).isoformat(),
            'monthly_end': start.isoformat(), 'award_start': year_start.isoformat(),
            'award_end': d.isoformat()}


def amount(r):
    if r.get('amount_kind') != 'award':
        return None, '非最终中标总价'
    if r.get('currency') != 'CNY':
        return None, '非明确人民币'
    s = str(r.get('amount_raw') or '').strip()
    if any(t in s for t in ['%', '‰', '/年', '/吨', '不超过', '上限']):
        return None, '费率/单价/上限'
    m = re.fullmatch(r'[￥¥]?\s*([\d,]+(?:\.\d+)?)\s*(亿元|万元|元)', s)
    if not m:
        return None, '金额缺失或格式需人工核验'
    try:
        v = Decimal(m[1].replace(',', '')) * {'元': 1, '万元': 10000, '亿元': 100000000}[m[2]]
    except InvalidOperation:
        return None, '金额无效'
    if v <= 0:
        return None, '非正金额需人工核验'
    return v.quantize(Decimal('.01')), None


def identity(r):
    fields = [r.get('buyer'), r.get('project_id'), r.get('lot')]
    if not all(fields):
        raise ValueError('采购人/编号/标包缺失，不能自动去重')
    return '|'.join(str(x).strip() for x in fields)


def analyze(rows, start, end, include_index=False):
    start, end = day(start), day(end)
    if start > end:
        raise ValueError('开始日期晚于结束日期')
    excluded, candidates = [], {}
    for r in rows:
        r = r.copy()
        try:
            k = identity(r)
            d = day(r['published_date'])
            if not start <= d <= end:
                raise ValueError('窗口外')
            if r.get('notice_type') not in ('award', 'correction'):
                raise ValueError('非最终中标/更正')
            if r.get('notice_type') == 'correction' and not r.get('corrects_award'):
                raise ValueError('非中标更正')
            # Select latest version BEFORE quality filtering: never resurrect an obsolete award.
            v = day(r.get('version_date', r['published_date']))
            if v > end:
                raise ValueError('版本晚于截止日')
            if k in candidates:
                old_v, old = candidates[k]
                ignored = {'id', 'url', 'version_date', 'retrieved_date'}
                same = {k: x for k, x in r.items() if k not in ignored} == {k: x for k, x in old.items() if k not in ignored}
                if v < old_v or (v == old_v and same):
                    excluded.append({'id': r['id'], 'reason': '重复/旧版'})
                    continue
                if v == old_v and r != old:
                    old['verification'] = 'conflict_needs_review'
                    raise ValueError('同日版本冲突需人工核验')
                excluded.append({'id': old['id'], 'reason': '被新版替代'})
            candidates[k] = (v, r)
        except (ValueError, KeyError) as e:
            excluded.append({'id': r.get('id'), 'reason': str(e)})
    accepted = []
    for _, r in candidates.values():
        reason = None
        if r.get('verification') not in (('full_text', 'official_index') if include_index else ('full_text',)):
            reason = '未核验原文'
        elif r.get('relevant') is not True:
            reason = '非实质相关或待判断'
        elif r.get('scope') != 'core':
            reason = '扩展层单列'
        if reason:
            excluded.append({'id': r['id'], 'reason': reason})
        else:
            accepted.append(r.copy())
    # Do not mix project totals with lots of the same project.
    totals = {(r['buyer'], r['project_id']) for r in accepted if r['lot'] == 'ALL'}
    kept = []
    for r in accepted:
        if r['lot'] != 'ALL' and (r['buyer'], r['project_id']) in totals:
            excluded.append({'id': r['id'], 'reason': '已有项目总额，剔除标包'})
        else:
            kept.append(r)
    values, categories, years = [], {}, {}
    bins = {'[0,50万)': 0, '[50万,100万)': 0, '[100万,500万)': 0, '[500万,+∞)': 0}
    for r in kept:
        v, why = amount(r)
        r['amount_cny'] = str(v) if v is not None else None
        r['amount_note'] = why
        cat = r.get('category', '未分类')
        categories[cat] = categories.get(cat, 0) + 1
        year = r['published_date'][:4]
        years[year] = years.get(year, 0) + 1
        if v is not None:
            values.append(v)
            key = list(bins)[0 if v < 500000 else 1 if v < 1000000 else 2 if v < 5000000 else 3]
            bins[key] += 1
    summary = {'record_count': len(kept), 'amount_count': len(values),
               'unknown_amount_count': len(kept) - len(values),
               'sum_cny': str(sum(values, Decimal(0))),
               'median_cny': str(statistics.median(values)) if values else None,
               'min_cny': str(min(values)) if values else None,
               'max_cny': str(max(values)) if values else None,
               'bins': bins, 'category_counts': categories, 'year_counts': years}
    return {'window': [str(start), str(end)], 'analysis_mode': '含未核验官方索引的线索敏感性分析' if include_index else '原文核验严格口径', 'summary': summary, 'accepted': kept, 'excluded': excluded}


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'ESGHomework/1.0 (public research)'})
    with urllib.request.urlopen(req, timeout=12) as response:
        data = response.read(2000001)
        if len(data) > 2000000:
            raise ValueError('响应超过2MB限制')
        return data, response.headers.get_content_charset() or 'utf-8'


def monthly(rows, start, end):
    start, end = day(start), day(end)
    groups = {'current_disclosures': [], 'background': [], 'subsequent': [], 'needs_review': []}
    seen = set()
    for r in rows:
        try:
            if r['url'] in seen:
                continue
            seen.add(r['url'])
            published = day(r['published_date'])
            if r.get('verification') != 'full_text':
                groups['needs_review'].append(r)
            elif published < start:
                groups['background'].append(r)
            elif published > end:
                groups['subsequent'].append(r)
            else:
                groups['current_disclosures'].append(r)
        except (ValueError, KeyError, TypeError):
            groups['needs_review'].append(r)
    return {'window': [str(start), str(end)], 'groups': groups,
            'note': '按发布日期分层；旧事件本月披露与本月新事件仍需区分；跨站事件去重由模型核验。'}


def extract(content, query, limit=3):
    content = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', content, flags=re.S | re.I)
    content = html.unescape(re.sub(r'<[^>]+>', ' ', content))
    sentences = re.split(r'[。！？\n]+', re.sub(r'[ \t]+', ' ', content))
    words = query.split()
    ranked = sorted(enumerate(sentences), key=lambda x: (-sum(w.lower() in x[1].lower() for w in words), x[0]))
    selected = sorted([(i, s.strip()) for i, s in ranked if 20 <= len(s.strip()) <= 400][:limit])
    return '。'.join(s for _, s in selected)[:600]


def search(queries, max_results):
    result, errors, rejected, seen = [], [], [], set()
    for query in queries:
        url = 'https://www.bing.com/search?' + urllib.parse.urlencode({'q': query, 'format': 'rss'})
        try:
            raw, _ = fetch(url)
            items = ET.fromstring(raw).findall('.//item')[:max_results]
            if not items:
                errors.append({'query': query, 'error': '检索返回空；不能认定没有相关新闻'})
            for item in items:
                link = item.findtext('link') or ''
                title = item.findtext('title') or ''
                description = item.findtext('description') or ''
                meaningful = [w for w in query.split() if not re.fullmatch(r'[0-9年月日./-]+', w)]
                if meaningful and not any(w.casefold() in (title + ' ' + description).casefold() for w in meaningful):
                    rejected.append({'query': query, 'title': title, 'url': link, 'reason': '标题与摘要均未命中查询实质词，不能作为相关线索'})
                    continue
                if link in seen:
                    continue
                seen.add(link)
                row = {'query': query, 'title': item.findtext('title'), 'url': link,
                       'verification': 'search_only', 'published_date': None,
                       'retrieved_at': datetime.now(timezone.utc).isoformat()}
                try:
                    body, enc = fetch(link)
                    row['extractive_summary'] = extract(body.decode(enc, errors='replace'), query)
                    row['body_sha256'] = hashlib.sha256(body).hexdigest()
                    row['verification'] = 'fetched_unreviewed'
                except Exception as e:
                    row['fetch_error'] = str(e)
                result.append(row)
        except Exception as e:
            errors.append({'query': query, 'error': str(e)})
    return {'provider': 'Bing public RSS (best effort)', 'queries': queries,
            'coverage': 'partial' if errors or not result or any('fetch_error' in r for r in result) else 'search_completed',
            'warning': '自动摘要非事实核验；搜索索引不保证完整，日期需人工/模型核验。',
            'results': result, 'rejected': rejected, 'errors': errors}


def monitor(rows, state, now):
    current = datetime.fromisoformat(now)
    if current.utcoffset() is None:
        raise ValueError('now必须含时区')
    if current.utcoffset() != timedelta(hours=8):
        raise ValueError('日报时刻必须为北京时间+08:00')
    out, pending = [], []
    sent = state.get('sent', {})
    seen = set()
    for r in rows:
        try:
            if r.get('notice_type') not in ('tender', 'correction') or r.get('relevant') is not True:
                raise ValueError('非相关新招标/更正')
            published = day(r['published_date'])
            if not (current.date() - timedelta(days=7) <= published <= current.date()):
                raise ValueError('回看窗口外')
            if r.get('verification') != 'full_text':
                raise ValueError('待原文核验')
            deadline = datetime.fromisoformat(r['deadline'])
            if deadline.utcoffset() is None:
                raise ValueError('截止时刻缺少时区')
            if deadline <= current:
                raise ValueError('已截止')
            if r.get('registration_deadline'):
                reg = datetime.fromisoformat(r['registration_deadline'])
                if reg.utcoffset() is None or reg <= current:
                    raise ValueError('文件获取/报名已截止或时区不明')
            else:
                raise ValueError('文件获取/报名截止时间待核验')
            k = identity(r)
            # Retrieval metadata, local IDs and mirror URLs change without a business change.
            notified_fields = ('title', 'buyer', 'project_id', 'lot', 'notice_type', 'published_date',
                               'version_date', 'deadline', 'registration_deadline', 'budget_raw',
                               'requirements', 'service_scope')
            payload = {field: r.get(field) for field in notified_fields}
            version = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            outbox_id = hashlib.sha256((k + version).encode()).hexdigest()
            if outbox_id not in sent and outbox_id not in seen:
                seen.add(outbox_id)
                out.append({'outbox_id': outbox_id, 'record': r})
        except (ValueError, KeyError) as e:
            pending.append({'id': r.get('id'), 'reason': str(e)})
    return {'as_of': now, 'status': 'local_outbox_only', 'ready': out, 'pending_or_excluded': pending,
            'note': '台账重放未执行联网覆盖检查；无新增不等于全网零新增；ack仅用于真实发送成功后。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('window'); p.add_argument('--as-of', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('monthly'); p.add_argument('--input', required=True); p.add_argument('--start', required=True); p.add_argument('--end', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('search'); p.add_argument('--query', action='append', required=True); p.add_argument('--max-results', type=int, default=3); p.add_argument('--out', required=True)
    p = sub.add_parser('analyze'); p.add_argument('--input', required=True); p.add_argument('--start', required=True); p.add_argument('--end', required=True); p.add_argument('--include-official-index', action='store_true'); p.add_argument('--out', required=True)
    p = sub.add_parser('monitor'); p.add_argument('--input', required=True); p.add_argument('--state', required=True); p.add_argument('--now', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('ack'); p.add_argument('--outbox', required=True); p.add_argument('--state', required=True); p.add_argument('--id', action='append', required=True); p.add_argument('--receipt', required=True)
    a = parser.parse_args()
    if a.command == 'window':
        result = window(a.as_of)
    elif a.command == 'monthly':
        result = monthly(read(a.input), a.start, a.end)
    elif a.command == 'search':
        if not 1 <= a.max_results <= 10:
            parser.error('max-results应在1至10之间')
        result = search(a.query, a.max_results)
    elif a.command == 'analyze':
        result = analyze(read(a.input), a.start, a.end, a.include_official_index)
    elif a.command == 'monitor':
        state = read(a.state) if Path(a.state).exists() else {'sent': {}}
        result = monitor(read(a.input), state, a.now)
    else:
        state = read(a.state) if Path(a.state).exists() else {'sent': {}}
        valid = {r['outbox_id'] for r in read(a.outbox)['ready']}
        if not set(a.id) <= valid:
            parser.error('ack包含不属于待发送箱的ID')
        for oid in a.id:
            state.setdefault('sent', {})[oid] = {'receipt': a.receipt, 'ack_at': datetime.now(timezone.utc).isoformat()}
        write(a.state, state)
        print('已按提供的发送回执更新状态；脚本未执行外部推送。')
        return
    write(a.out, result)
    print(json.dumps(result.get('summary', {'command': a.command, 'output': a.out}), ensure_ascii=False))


if __name__ == '__main__':
    main()
