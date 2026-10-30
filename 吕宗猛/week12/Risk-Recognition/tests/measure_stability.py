# 合成样本图的判定稳定性测量（重复 N 次，统计分布）
# 用法：python tests/measure_stability.py [次数]
import collections
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "tests" / "samples"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
TARGETS = ["synthetic_corridor_ebike.jpg", "corridor_clutter_high_boxes.jpg",
           "corridor_door_clutter.jpg", "non_corridor_pingpong.jpg"]

report = {}
for name in TARGETS:
    p = SAMPLES / name
    if not p.exists():
        continue
    import base64
    b64 = base64.b64encode(p.read_bytes()).decode()
    dist = collections.Counter()
    times = []
    for _ in range(N):
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/recognize",
            data=json.dumps({"image": "data:image/jpeg;base64," + b64}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                b = json.loads(r.read().decode("utf-8"))
            dist[b.get("category")] += 1
            times.append(int((time.time() - t0) * 1000))
        except Exception as e:
            dist["ERROR"] += 1
    report[name] = {"n": N, "distribution": dict(dist),
                    "elapsed_ms_min": min(times) if times else None,
                    "elapsed_ms_max": max(times) if times else None}
    print(name, dict(dist), f"{min(times) if times else '-'}~{max(times) if times else '-'}ms")

out = ROOT / "tests" / "stability.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved", out)
