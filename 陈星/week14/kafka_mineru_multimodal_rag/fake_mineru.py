"""离线替身：模拟 `mineru parse <pdf> -o <输出> --pages all` 的行为。

只用于 smoke_e2e.py 验证链路；真实解析效果请看 README 里 MinerU 4.2.1 的运行记录。
输出格式与 MinerU 4.x 的 Markdown 一致：页注释、标题、表格、图片定位符。
"""
import json
import sys
import time
from pathlib import Path

args = sys.argv[1:]
out = Path(args[args.index("-o") + 1])
print("fake mineru:", " ".join(args))
time.sleep(2)
# 与真实 MinerU 一致：-o 指定的是输出文件路径，父目录必须由调用方创建好
if out.parent.is_dir():
    out = out / "parse_output"
out.write_text("""<!-- page 1 of 2 -->

## 01 研究方法

本报告采用分章节检索与核验的方法，先拆分研究目标，再逐章节检索、写作。

| 步骤 | 说明 |
| --- | --- |
| 拆分 | 把研究目标拆成子问题 |
| 检索 | 每个子问题检索并整理证据 |
| 核验 | 对关键结论做交叉验证 |

<!-- page 2 of 2 -->

## 02 系统架构

前端、Kafka、worker 与 MinerU 串成一条解析链路，索引写入后才可以检索。

![Image block](doc:smoke-fixture/tier:basic/page:2/block:3)
""", encoding="utf-8")
print("Written to", out)
