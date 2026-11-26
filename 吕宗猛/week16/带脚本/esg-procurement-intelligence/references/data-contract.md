# 数据契约与脚本接口

Python 3.10+、标准库。金额使用 Decimal；JSON 金额值用字符串，禁止浮点。脚本处理证据中已经明确的事实，不调用网络、不猜测类别、不读取通知凭据。

## 输入文档

UTF-8 JSON，顶层 `records`、`sources` 必须是数组，可提供 `coverage` 对象保存研究范围、查询计划、已检索/缺失地区和已知缺口。所有日期为 ISO `YYYY-MM-DD`；`deadline` 允许带时区的 ISO 日期时间。来源与摘录都是真实研究产物，不能用示例代替正式来源。

```json
{
  "coverage": {"regions_requested": "中国全国", "limitations": ["公开样本，非全量"]},
  "sources": [{
    "source_id": "official-001", "url": "https://example.org/notice/001",
    "publisher": "采购人官方门户", "checked_at": "2026-11-25T09:00:00+08:00",
    "status": "ok", "region": "广东", "queries": ["碳核算 中标"],
    "notes": "正文及附件已核验"
  }],
  "records": [{
    "record_id": "notice-001-v1", "project_number": "采购编号-001",
    "buyer": "采购人全称", "lot_id": "whole", "procurement_round": "1",
    "title": "碳排放核算技术服务", "category": "service", "region": "广东",
    "notice_type": "award", "status": "awarded", "published_date": "2026-10-30",
    "award_date": "2026-10-29", "revision": 1, "source_id": "official-001",
    "verification": "verified", "inclusion_reason": "碳排放核算服务",
    "evidence": [{"source_id": "official-001", "locator": "正文中标金额段", "excerpt": "中标金额84.2万元"}],
    "winners": ["供应商甲"], "contract_period": "以原公告为准，未披露则留空",
    "amounts": [{"kind": "award", "raw": "84.2万元", "value": "84.2", "unit": "万元", "currency": "CNY", "tax_basis": "unspecified", "scope": "lot_total"}]
  }]
}
```

`example.org` 是格式示例，不是可核验证据。正式记录的 `verification: verified` 应由研究者在读过原文后设置。

## 身份、版本、状态

- `record_id`：每份公告/更正的标包快照唯一；重复 ID 视为输入错误。多标包同一公告可提供相同 `announcement_id`；未提供时按原文URL、日期和公告类型识别公告文档数，记录行数另保留。
- 身份优先 `project_id`（研究者确认的稳定编号）；否则 `project_number + buyer`。同时使用 `lot_id` 和 `procurement_round`。无身份时以记录建立孤立待核实项目，避免错合并。
- `lot_id: whole` 仅表示核实为整体、未分包项目；未知标包用空值，程序标记待核实。整包总额不能复制成多个分包金额。
- `procurement_round` 区分重招和编号复用；未知轮次用空值并标记。不得自动把新轮次结果并入旧轮次。
- `status`：`tender`、`candidate`、`awarded`、`contracted`、`terminated`、`award_revoked`、`retender`、`expired`、`unknown`。
- `category`：`service`、`software_data`、`equipment_engineering`、`mixed`；未知为待核实，不自动归入混合。
- 快照按公告日期、明确的 `revision` 排序。同日期同版本的不同业务内容视为冲突，不默默选择金额。完全相同的转载只保留一条当前业务快照，但保存所有记录及来源。
- `is_partial: true` 不能直接作为完整状态。稀疏更正先由研究者根据明确关联原公告，建立完整且各事实都有来源的快照；脚本保留未处理的稀疏更正并排除该标包主统计。
- `supersedes` 可列被明确替代的 `record_id`，用于同日期版本裁决；只接受同一身份的明确引用。更正要更新完整金额数组，避免旧成交金额仍残留。撤销/终止保留旧版本，最新状态排除金额统计。
- 脚本不自动把结果公告的 `published_date` 当作 `award_date`。实际成交日期可null；默认统计按核验的中标/成交公告发布日期。归一时从同采购轮次已核验的 `notice_type: award/result/中标/成交` 公告版本保留 `award_notice_published_date`，避免后续更正移动旧成交的统计日期。结果被撤销后重新发布的有效结果，采用撤销之后的已确认结果公告日期；无法确认原结果公告日期时单列需核实。

## 金额

每个金额对象保存 `kind`、`raw`、`value`、`unit`、`currency`、`tax_basis`、`scope`；可附 `source_id`、`contract_period`、备注。`scope` 取 `lot_total`、`project_total`、`unit_price`、`framework` 或 `unknown`。

| `kind` | 含义 |
| --- | --- |
| `budget` | 招标预算 |
| `ceiling` | 最高限价 |
| `candidate_quote` | 候选报价 |
| `award` | 已确认中标/成交总价 |
| `contract` | 合同总价 |
| `unit_price` | 单价，不进入总额统计 |
| `framework_cap` | 框架上限，不等于确定采购金额 |

明确 `value` + `unit` 优先；未给 value 时只对整体形如 `84.2万元` 的单一确定原文解析。支持元/万元/亿元、`base`/`thousand`/`million`/`billion`；必须显式提供币种，不从符号或中文单位猜测。逗号只接受标准三位分组。

包含“约”、范围、“不少于”、百分比、多笔金额及科学计数法的原文不能自动解析。精度不默默舍入；`base_amount` 是 Decimal 的普通十进制字符串。负金额、浮点、币种/单位未知、字段与原文明显数字冲突会标记待核实；未披露金额保持 null，不用0代替。

税口径为 `included`、`excluded`、`unspecified`，按币种和税口径分别统计。不换汇、不把含税与不含税相加后作为直接可比总额。不年化多年合同，不把联合体金额复制给每位成员。

主成交金额仅使用已核验、身份及版本清楚、类别已确认的当前 `awarded` / `contracted` 状态中的唯一有效 `award` 总金额。`scope` 必须是 `lot_total`，或经确认未分包的 `whole` 项目 `project_total`。一个标包多笔不同 `award` 总金额、框架金额或金额歧义均标记，避免任选一个数字。`contract` 使用同样规则另算，不能与 `award` 相加。

## CLI 与产物

### 费率与上限

费率单独存为`rates`数组，不能写入`amounts`伪装金额。例如：

```json
{"rates": [{"kind": "ceiling", "raw": "费率最高100%", "value": "100", "unit": "percent", "basis": "采购文件规定的检测收费基数（待核实细则）", "scope": "lot"}]}
```

`kind`支持`ceiling`、`quote`、`award`；`scope`支持`project`、`lot`、`item`；数值为非负十进制字符串或整数，浮点拒绝。`basis`保留原收费基数或其待核实说明，不根据费率和预算推导确定价。费率数值、性质、基数与范围参与业务指纹，因此100%改为90%或收费基数改变会产生内容变更；100与100.00等数值精度表示不产生重复变更。旧记录的`rate_ceiling`文本也参与指纹，建议新采集改用结构化`rates`。

增加指纹业务字段后，旧版试跑状态第一次升级可能产生一次字段补全变更。本次尚未部署定时运行；示范重新建立带费率字段的状态基线，同时保存旧试跑输出，随后重复运行验证无新增，不把字段迁移写成官方公告更正。

```text
window --as-of YYYY-MM-DD [--months 24]
normalize --input evidence.json --output normalized.json
stats --input normalized.json --output statistics.json [--markdown statistics.md] [--as-of YYYY-MM-DD] [--from YYYY-MM-DD --to YYYY-MM-DD] [--date-basis published_date|award_date]
monitor --input normalized.json --state monitor-state.json --output daily.md [--as-of YYYY-MM-DD] [--lookback-days 7] [--due-days 3] [--dry-run]
```

`normalize` 输出当前标包快照、全部公告版本、金额归一结果、issues、冲突及 sources；没有静默清除原文或失败来源。缺失日期和身份会出现在 issues。

`stats` 输出窗口、项目/标包/公告数量、四类统计、币种/税口径金额分组、缺失率、最小/四分位/中位/最大，及地区、采购人、公告季度、联合供应商主体分组。默认主窗口按已确认结果公告发布日期；`--date-basis award_date` 才使用实际成交日期并单列缺失日期。`--start` / `--end` 是 `--from` / `--to` 的同义参数。不满足条件的记录计入 exclusions。金额缺失率以窗口内、当前状态有效的成交标包为分母，不以全部招标公告为分母；合同金额另表。

`monitor` 输出新增、内容变更、延期、终止/撤销、临近截止，以及来源失败/未核实线索。状态只存业务指纹和历史截止提醒，不把检索时间或转载来源变更当成新机会。状态文件通过单次本地原子替换写入；同一状态避免并发写入。覆盖失败时保留最近完整成功日及 `pending_query_start`，即使首次开始后连续失败也能补查早期窗口。

监控研究完成时 `coverage` 必须明确记录 `search_completed: true`、`query_start: YYYY-MM-DD`、`searched_through: YYYY-MM-DD`。只有实际检索跨度覆盖本次建议窗口且来源均ok，才推进最近完整成功日；仅导入已有历史公告不代表今日检索完整。来源完整只针对实际提供且已检索的来源集合，仍不等于全国全量。

各命令成功返回0，输入/日期/状态格式错误返回2并解释，不读秘密或发送外部消息。
