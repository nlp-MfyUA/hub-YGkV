# 联网检索与自动证据摘要

用 Python 配置查询及校验结果，用 ChatGPT 的公开网页搜索和原文读取批量采集，再用 Python 筛选并生成带原文链接的证据简报。以下命令均用 `python3` 运行。Python 部分可使用已有的 JSON 证据包离线重放。

## 检索配置

- 月报用 `python3 scripts/esg_pipeline.py plan --profile monthly --start YYYY-MM-DD --end YYYY-MM-DD`。为非默认企业明确传入 `--company --ticker --industry --peers`，并用 `--query` 增补当地监管或交易所检索。
- 投标分析用 `python3 scripts/esg_pipeline.py plan --profile tender --start YYYY-MM-DD --end YYYY-MM-DD`。快报加 `--mode live`。用 `--max-open` 限制正文打开数量。长区间按季度拆查。根据待核项、缺口及本轮证据控制查询次序并增补精确关键词，注意同一轮的网页覆盖有限。
- 将计划 JSON 写入工作目录，例如 `esg-plan.json`。在具备公开搜索工具的 ChatGPT code mode 中，读取本 Skill 的 `scripts/chatgpt_search.js`，执行其导出函数并把返回对象存成 `esg-evidence.json`。以下代码示例假设已将路径改为真实绝对路径，脚本路径只接受已安装的 Skill 代码。

```javascript
const [source, planFile] = await Promise.all([
  tools.exec_command({ cmd: "cat '<installed-script-absolute-path>'", max_output_tokens: 8000 }),
  tools.exec_command({ cmd: "cat '<plan-absolute-path>'", max_output_tokens: 10000 }),
]);
if (source.exit_code || planFile.exit_code) throw new Error("Could not open the installed script or plan");
const collect = eval(source.output);
const packet = await collect(JSON.parse(planFile.output));
const content = JSON.stringify(packet, null, 2).split("\n").map(line => "+" + line).join("\n");
await tools.apply_patch("*** Begin Patch\n*** Add File: esg-evidence.json\n" + content + "\n*** End Patch");
text(packet.coverage);
```

仅对安装目录中的脚本运行 `eval`。网页文本作为 JSON 数据交给 Python。没有 code mode 时，可用环境提供的公开搜索和打开网页工具执行同一计划，并构造同样的证据包。JSON 顶层含 `documents`，每条记录为 `id,title,url,text,outcome,lane,ref`，有正文时 `outcome=opened`，打不开时用 `unavailable`。行范围有跳跃时用 `gap=true`。顶层可附 `queries,errors,coverage`。

## 校验和交付

- 运行 `python3 scripts/esg_pipeline.py analyze --profile PROFILE --start YYYY-MM-DD --end YYYY-MM-DD --markdown esg-summary.md esg-evidence.json`，可将 stdout 重定向保存为 JSON。招标快报沿用 `--mode live`。非默认公司月报继续传入同一 `--ticker`，过滤巨潮其他股票代码的披露。已核实为采购人、代理或发布机构的域名可用 `--trusted-domain` 补充。
- 核查摘要中检索失败、日期未知、来源待核、缺失或冲突金额。以正文或可核对的披露档案日期为准，签发日、事件日、招标生效日保留独立含义。项目总额优先用公告的明确值。仅在可验证的完整标包结果区相加，存在跳行、未读到后续章节、非固定价或结果冲突时检查原公告。
- 证据卡和金额为报告底稿。月报对关键事件复核时间和原文，补写对客户的影响与行动建议。投标用已有汇总脚本对核验后的完整 CSV 统计分布。快报逐条核实是否公开可参与、最新报名和投标截止及更正，去重后才发布。原数据只在用户需要复算或复查时提供。
- 公开搜索结果和网页访问范围会变。发布前记录实际查询数、正文打开数、失败和补查；同一固定证据包可复现筛选与统计。
