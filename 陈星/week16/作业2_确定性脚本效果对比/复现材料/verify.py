import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import esg_pipeline as p

work = Path(__file__).parent
root = Path('/home/agent/.codex/skills/remote-skills')
install = {
    'monthly': root / 'skill-6b091ce94b848191ad9eec8b9a7fc273',
    'awards': root / 'skill-6b091d09dc188191a3295f99865a5e1f',
}
windows = {'monthly': ('2026-10-01', '2026-10-31'), 'awards': ('2025-01-01', '2026-11-26')}
ground = {'M02':'review', 'M03':'out_of_window', 'M04':'out_of_window', 'M07':'included',
          'M09':'included', 'M11':'included', 'M12':'out_of_window', 'M13':'included',
          'M14':'duplicate', 'A01':'review', 'A02':'included', 'A03':'included',
          'A04':'included', 'A05':'included', 'A06':'not_in_scope', 'A07':'not_in_scope',
          'A08':'review', 'A09':'included', 'A10':'included', 'A11':'included',
          'A12':'included', 'A13':'duplicate'}
ground.update(dict.fromkeys(('M01','M05','M06','M08','M10'), 'review'))
amounts = {'A02':38979000, 'A03':9700000, 'A04':220000, 'A05':189500,
           'A09':986799, 'A10':None, 'A11':480000, 'A12':230000}
baseline = {}
for line in (work/'baseline.md').read_text().splitlines():
    m = re.match(r'\| ([MA]\d\d) \| (\w+) \| [^|]+ \|(.*)',line)
    if m:
        amount = None
        if m[1].startswith('A'):
            cell = m[3].split('|')[0].strip()
            if cell:
                amount = int(cell)
        baseline[m[1]] = (m[2], amount)
assert set(baseline) == set(ground)

combined = {}
initial_rows = {}
result_metrics = {}
for name in ('monthly','awards'):
    start, end = windows[name]
    args = [sys.executable, str(install[name]/'scripts/esg_pipeline.py'), 'analyze',
            '--profile', 'monthly' if name=='monthly' else 'tender', '--start',start,
            '--end',end, str(work/f'{name}-input.json')]
    runs = [subprocess.check_output(args) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    d = json.loads(runs[0])
    (work/f'{name}-script.json').write_bytes(runs[0])
    combined.update({row['id']:row for row in d['cards']})
    initial = json.loads((work/f'{name}-initial.json').read_text())
    initial_rows.update({row['id']:row for row in initial['cards']})
    result_metrics[name] = {'runs_equal': len(runs), 'count':len(d['cards']),
                            'counts': d['counts'], 'priced': d['priced'],
                            'sum': d['amount_total_yuan'], 'initial_priced':initial['priced'],
                            'initial_sum':initial['amount_total_yuan'],
                            'sha256':hashlib.sha256(runs[0]).hexdigest()}
assert sum(baseline[key][0] == status for key, status in ground.items()) == len(ground)
assert sum(combined[key]['status'] == status for key, status in ground.items()) == len(ground)
assert sum(initial_rows[key]['status'] == status for key, status in ground.items()) == len(ground)-1
assert all(baseline[key][1] == value for key, value in amounts.items())
parsed = {key: Decimal(combined[key]['amount_yuan']) if combined[key]['amount_yuan'] else None
          for key in amounts}
assert parsed == amounts
assert sum(value for value in amounts.values() if value is not None) == 50785299
assert Decimal(result_metrics['awards']['sum'])-Decimal(result_metrics['awards']['initial_sum']) == 9700000+986799

checks = [
    ('leap day', list(p.dates('2024年2月29日')) == [date(2024,2,29)]),
    ('invalid leap day', list(p.dates('2025年2月29日')) == []),
    ('effective date', p.publication('生效时间：2026-10-20','https://www.example.org/a') == (None,None)),
    ('tracked URL', p.canonical('https://www.example.org/a?id=5&utm_source=x#p') == 'https://www.example.org/a?id=5'),
    ('money decimal in ten-thousands', p.award_amount('总中标金额 | ¥970.000000 万元(人民币)')[0] == 9700000),
    ('Chinese uppercase RMB', p.award_amount('成交价格:壹拾捌万玖仟伍佰元整')[0] == 189500),
    ('too-small fraction', p.award_amount('中标价:1.00001元')[0] is None),
    ('budget only', p.award_amount('最高限价:999万元\n代理费:2000元')[0] is None),
    ('candidate excluded', p.classify_award('碳足迹中标候选人公示') == 'excluded'),
    ('tender opportunity', p.classify_award('碳核查竞争性磋商公告') == 'opportunity'),
    ('empty ledger', not p.monthly_facts('', '')),
    ('conflicting totals', p.award_amount('总中标金额:4万元\n总中标金额:5万元')[0] is None),
]
package = '三、采购结果\n合同包1(核查):\n供应商名称 | 中标(成交)金额\n--- | ---\n已核供应商 | 120元'
checks.extend([
    ('truncated package', p.award_amount(package)[0] is None),
    ('complete single package', p.award_amount(package+'\n四、主要标的信息')[0] == 120),
    ('gap reported', p.award_amount(package+'\n四、主要标的信息', allow_packages=False) == (None,'未识别到唯一固定总额')),
    ('date window split', list(p.quarterly(date(2025,12,31),date(2026,1,1))) == [(date(2025,12,31),date(2025,12,31)),(date(2026,1,1),date(2026,1,1))]),
])
for label, ok in checks:
    assert ok, label
for name in ('monthly','tender'):
    dates = ('2026-10-01','2026-10-31') if name=='monthly' else ('2026-09-01','2026-09-30')
    path = work/f'{name}-live-final.json'
    run = subprocess.check_output([sys.executable, str(work/'esg_pipeline.py'), 'analyze','--profile',name,
                                   '--start',dates[0],'--end',dates[1],str(path)])
    live = json.loads(run)
    packet = json.loads(path.read_text())
    result_metrics[name+'-live'] = {**packet['coverage'], 'queries': len(packet['queries']),
                                     'counts':live['counts'], 'amount':live['amount_total_yuan']}
    (work/f'{name}-live-final-result.json').write_bytes(run)
result_metrics['edge_checks'] = len(checks)
result_metrics['status_accuracy'] = {'baseline': len(ground), 'initial':len(ground)-1,'revised':len(ground)}
print(json.dumps(result_metrics,ensure_ascii=False,indent=2))
