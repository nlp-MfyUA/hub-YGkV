---
name: esg-tender-watch
description: 自主搜索近两年ESG与双碳中标信息，用脚本规范日期、去重、金额统计和每日招标待发送状态。
---

# ESG投标汇总（脚本辅助版）

默认全国、Asia/Shanghai、截止日前两个日历年，两端包含。先阅读 [references/method.md](references/method.md)，保留无脚本版的相关性、公告类型、证据与推送规则；字段见 [references/schema.md](references/schema.md)。

## 检索与中标分析

1. 在当前skill目录运行 `python scripts/esg_pipeline.py window --as-of 2026-11-26 --out output/window.json`，实际任务替换日期。
2. 自主生成ESG、报告、核查、碳足迹、双碳规划等关键词，按年份和地区检索。可运行 `python scripts/esg_pipeline.py search --query "ESG 可持续发展报告 中标 2025" --query "碳排放 核查 中标 2026" --out output/search.json`，补充官方平台和可用联网工具。
3. 打开原文，模型确认相关性、类型、项目/标包、原始金额、币种和日期，写入JSON数组。下载成功不等于核验成功，摘要不能自动设为full_text。项目编号缺失不要生成看似真实编号；转人工复核，不得进入正式统计。
4. `python scripts/esg_pipeline.py analyze --input output/awards.json --start 2024-11-26 --end 2026-11-26 --out output/analysis.json` 输出严格统计和排除理由。脚本按采购人+编号+标包比较版本，优先项目总额而不叠加标包，以Decimal解析元/万元/亿元，缺失和费率记null。
5. 确需分析线索偏差时可加 `--include-official-index`，输出必须明确是含未核验索引的敏感性分析。标注这种选择不能提高事实可信度。统计后的热点解释、资格判断和商务建议由模型完成。

## 每日监控

每天先联网回看7日，核验后保存招标数组，再运行：

`python scripts/esg_pipeline.py monitor --input output/tenders.json --state output/state.json --now 2026-11-26T18:00:00+08:00 --out output/outbox.json`

时间必须是实际北京时间。模型检查更正/撤销公告、文件获取期限和资格，补齐日报。outbox命令只是台账回放，不执行联网覆盖检查，也不发送，不因空列表声称“全网无新增”。字段变化产生新版本；跨URL、标题变化的实质同一事件仍需模型核验。

只有渠道实际返回成功回执后，才用 `ack --outbox output/outbox.json --state output/state.json --id 实际ID --receipt 实际回执` 更新已发送状态；失败保留箱中待重试。单写进日报不是外部发送成功。未提供渠道和收件人时只生成本地日报；用户明确要求启用部署时再配置可用调度/发送工具。当前交付不自动安装定时任务。
