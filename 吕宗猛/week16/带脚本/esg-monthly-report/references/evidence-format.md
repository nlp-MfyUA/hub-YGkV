# 月报证据台账 v1

使用 UTF-8 JSON，未知日期使用 `null`，不猜测。脚本只检查确定性约束，不访问网络，不判定事实真实性或全文覆盖。

## 顶层

- `schema_version`：整数 `1`。
- `company`：报告主体名称。
- `period`：`start`、`end` 为 ISO 日期，左闭右开。
- `cutoff`：带时区的 ISO 研究截止时间，须不早于实际检索。
- `sources`、`claims`、`actions`、`coverage`：数组。候选事实不足时数组可以为空，但覆盖记录仍须解释。

## 来源 sources

每项包含 `id`（如 S001）、`title`、`publisher`、`url`、`published_date`（日期或 null）、`retrieved_at`（带时区）、`kind`、`verification`。

- `kind`：`official`、`company_disclosure`、`rating_provider`、`industry_media`、`other`。监管/标准制定机构的正式文件为 official。
- `verification`：`full_text`、`snippet`、`unavailable`。完整读取有关正文/附件后才能标 full_text；这个标签是研究者声明，不是程序认证。
- 可选 `local_path`：保存原文的位置，相对台账文件解释；填写时文件须存在。不要为未保存材料制造路径。
- 原文无日期时保留 null，引用时间不替代发布时间；说明如何确定事件月份。

## 事实 claims

每项必有 `id`（C001 等）、`category`、`text`、`status`、`entity_scope`、`date_basis`、`period_date`、`source_refs`。

- `category`：`policy`、`rating`、`standard`、`company`、`industry`、`peer`、`background`。
- `status`：`verified`、`lead`、`disputed`。verified 表示研究者已经核对原文，lead/disputed 不支撑强结论。
- `entity_scope`：`company`、`parent`、`subsidiary`、`peer`、`general`。
- `date_basis`：`publication`、`event`、`effective`、`background`；`period_date` 是本条事实的纳入日期。核实的本月事实须在报告窗口中，背景用 category/date_basis=background、period_date=null，并在正文标为历史背景。
- `source_refs`：`source_id`、`locator`、`excerpt`；verified 必须全部指向 full_text 来源并保存原文位置与短摘录。locator 例如“PDF 第 16 页，表 2”或“正文‘实施安排’第二段”。摘录只保留支持事实所需的少量文本。
- policy/standard 的 verified 事实需至少一个 official 来源，并提供非空 `applicability`，区分适用结论和待核实条件。
- rating 的 verified 事实需 rating_provider 或 company_disclosure 来源，以及 `rating_metadata`：`agency`、`scale`、`as_of`（日期）。公司自述评级应在 text 中明确归属。
- 可选 `event_date`、`effective_date` 保存不同日期，不能为进入本期改写日期。
- 可选 `metrics` 数组：没有数量事实时省略；凡用于重要比较或结论的数字都需记录。每项 `value`（十进制数字字符串）、`unit`、`period_start`、`period_end`（指标统计期左闭右开）、`boundary`、`method`。方法未披露可明确写“未披露，不能据此比较”，不能留空或虚构。范围不同的数字分项记录，不擅自归一化；缺失不是零。脚本不能从自由文本中识别所有数量遗漏，仍需内容复核。

## 行动 actions

每项 `id`、`triggered_by`（已核验事实 ID 数组）、`action`、`priority`（high/medium/low）、`owner_function`（建议职能）、`deliverable`、`validation`、`dependencies`（字符串数组）。内部情况未知时写明依赖，不假定建议职能已经接单。无核验事实支持的线索调查写在缺口栏，不作为已证实的行动依据。

## 覆盖 coverage

政策、评级、标准、公司、行业/同行各一项，`topic` 分别为 `policy`、`rating`、`standard`、`company`、`industry_peer`。每项有 `status`、`queries`（实际查询字符串数组）、`checked_source_ids`、`gaps`（具体限制数组）。

status 可为 `covered`、`partial`、`failed`、`no_verified_updates`。covered 仅表示本次计划的主要检查完成，不意味着全量；no_verified_updates 要有实际查询与检查来源；partial/failed 必须说明缺口。全文不可访问可记录 unavailable 来源。

## 最小形状示例

下例仅说明字段，来源不是生产证据；真实运行不能照搬内容。

```json
{
  "schema_version": 1,
  "company": "中国神华能源股份有限公司",
  "period": {"start": "2026-10-01", "end": "2026-11-01"},
  "cutoff": "2026-11-25T16:00:00+08:00",
  "sources": [{
    "id": "S001", "title": "原始材料标题", "publisher": "发布机构",
    "url": "https://example.org/document", "published_date": "2026-10-12",
    "retrieved_at": "2026-11-25T15:00:00+08:00",
    "kind": "official", "verification": "full_text"
  }],
  "claims": [{
    "id": "C001", "category": "policy", "text": "经过原文核验的事实",
    "status": "verified", "entity_scope": "general",
    "date_basis": "publication", "period_date": "2026-10-12",
    "applicability": "适用范围及需要核实的主体条件",
    "source_refs": [{"source_id": "S001", "locator": "正式文件第 3 条", "excerpt": "短原文摘录"}]
  }],
  "actions": [{
    "id": "A001", "triggered_by": ["C001"], "action": "核实适用主体并形成数据差距清单",
    "priority": "high", "owner_function": "建议由披露与数据治理职能评估",
    "deliverable": "适用性和数据字段清单", "validation": "与正式文件逐条复核",
    "dependencies": ["需取得主体分类及现有数据口径"]
  }],
  "coverage": [
    {"topic": "policy", "status": "covered", "queries": ["实际政策查询"], "checked_source_ids": ["S001"], "gaps": []},
    {"topic": "rating", "status": "failed", "queries": ["实际评级查询"], "checked_source_ids": [], "gaps": ["记录真实失败原因"]},
    {"topic": "standard", "status": "failed", "queries": ["实际标准查询"], "checked_source_ids": [], "gaps": ["记录真实失败原因"]},
    {"topic": "company", "status": "failed", "queries": ["实际公司查询"], "checked_source_ids": [], "gaps": ["记录真实失败原因"]},
    {"topic": "industry_peer", "status": "failed", "queries": ["实际行业查询"], "checked_source_ids": [], "gaps": ["记录真实失败原因"]}
  ]
}
```

## 校验调用

```powershell
python scripts/validate_evidence.py "<evidence.json>" --report "<report.md>" --output "<validation.json>"
```

输出 `valid`、errors、warnings 与计数。退出码 0 表示结构检查通过，1 为校验失败，2 为输入/读取失败。脚本不修改台账和报告；只有明确指定 output 才另写校验结果。摘要页或未核实线索不能被正文 `[C001]` 引用定义包装成已核验事实。
