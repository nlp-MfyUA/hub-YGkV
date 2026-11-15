# 全量入库进度快照 · 2026-11-15（入库 + E-LOAD + ChatBI 全量库验收全部完成）

> 本文件为唯一权威版本，数字全部来自数据库与产物实测。
> 旧版内容已废弃，不再保留。

## 当前状态：363 份解析入库完成；E-LOAD 8 项全过；ChatBI chat_eval 18/18、image_eval 9/10

## 总览（app/db/vuln.db）

| 项 | 数值 |
|---|---|
| v_report（active） | **342**（pentest 198 / retest 144） |
| v_vulnerability（active） | **1240** |
| v_retest_result（active） | **1142** |
| v_image_evidence（active） | **4958** |
| v_image_evidence_fts_docsize | **4958**（FTS 一致） |
| pdf_index | **342**（pass 293 / no_vulnerabilities 49 / fail **0**） |
| v_type_catalog | 19 |

完整性：`PRAGMA integrity_check = ok`，`foreign_key_check` 无违规。
测试：`pytest tests/` **160 passed**。

> 注：本轮任务给的 pdf_index 351（no_vulns 58）与实测不符。实测为 342 条
> （293 + 49），因为 363 份中有 21 份 `pending_review` 按设计不入 pdf_index。

## 批次 1（200 份渗透）

| parse_status | 数量 |
|---|---|
| pass | 145 |
| no_vulnerabilities | 48 |
| pending_review | 7 |
| fail | 0 |

- 8 份 MemoryError 已补跑成功（新增 137 条漏洞）
- 3 份原 fail 经复核为过期缓存，清缓存重跑后转为 `no_vulnerabilities`，旧产物备份于 `data/backup_stale_3/`

## 批次 2（163 份 = 6 渗透 + 157 回归）

| parse_status | 数量 |
|---|---|
| pass | 148 |
| no_vulnerabilities | 1 |
| pending_review | 14 |
| fail | **0** |

**9 份发改委回归模板已修**：`TextBlockLocator` 新增 `RETEST_ARABIC_TITLE_RE`
（`（1）漏洞名` 无等级后缀，仅当下一行为 `漏洞描述：` 时生效）。
合入前提已验证：**同团队 22 份已 pass 的报告记录数与 `raw_vuln_name` 列表零变化**，
9 份 fail 全部转为 pass 并入库，共 126 条 `v_retest_result`。

- 分段执行：2a1(18) / 2a2(18) / 2a3(19) / 2b(55) / 2c(53)
- 驱动脚本 `data/run_segment_incremental.py`：逐份解析后立即入库，OOM 只损失当前一份
- 2a、2c 各被系统 OOM 终止一次，均按已落盘产物续跑补齐，无数据丢失

## 复测匹配（v_retest_result，1142 条）

| match_confidence | 条数 |
|---|---|
| exact | 989 |
| fuzzy | 117 |
| none | 36 |
| **resolved（exact + fuzzy）** | **1106 / 1142 = 96.8%** |

### none 的根因分布（36 条）

| 类别 | 条数 | 说明 |
|---|---|---|
| A. 跨轮次父报告缺失（[FULL-007]） | **10** | id 171, 172, 173, 477–483 |
| B. 名称变体（已修规则未覆盖） | **21** | 其中 Locator 修复后新增 9 条（见下） |
| C. 已知个案（[FULL-004] / [FULL-005]） | **5** | id 22, 23, 29, 42, 79 |

**Locator 修复后新增的 9 条 none（id > 1016）全部为 B 类**：
1033, 1037, 1041, 1048, 1049, 1050, 1051, 1052, 1103。
其中 6 条（1033/1048/1049 + 1037/1041/1050/1051 中的多实例）根因是**父报告 `instance_index` 建模**
（[FULL-004] 同型），1 条是字形差异（1103 `信息泄露` vs `信息泄漏`，[FULL-005] 同型），
2 条是源报告本身没有对应条目。

**决策：不再增加名称归一化规则**（[FULL-008]）。B 类已分裂成多种互不重叠形态，且过半根因在父报告侧，加剥离规则无法解决。

## 待人工处理清单

### fail：0 份 ✅

发改委团队回归报告 31 份，**22 份原本 pass + 9 份修复后 pass = 31/31 全部通过**。

### pending_review：21 份

| 团队 | 份数 |
|---|---|
| 市场监管局（含药监局） | 12 |
| 财政局 | 5 |
| 国资委、科委和金融监管局 | 4 |

**其中 5 份已完成诊断（[FULL-010]，非解析缺陷）**：

| 报告 | 声明 vs 实际 | 结论 |
|---|---|---|
| 财政局非税收入管理系统回归-202610 | 8 vs 1 | **口径差异**：摘要按接口数，正文 1 条含 8 个 URL |
| 市监局行政处罚与执法监督系统回归-202606 | 5 vs 3 | **口径差异**：正文确为 3 条（附 [FULL-009] 状态文本丢失） |
| 市监局医疗器械追溯申报系统回归-202606 | 7 vs 5 | **口径差异**：正文确为 5 条（附 [FULL-009] 重名） |
| 市监局综合监管系统回归-202606 | 8 vs 6 | **口径差异**：正文确为 6 条 |
| 财政局综合办公系统回归-202606 | 5 vs 1 | **口径差异**：摘要按接口数，正文 1 条含 5 个 URL |

这 3 份市监局报告（行政处罚 / 医疗器械追溯申报 / 综合监管）已结案，**接受现有条数**。

**剩余待人工核对 16 份**，按团队：市监局 9、财政局 3、国资委科委 4。

## tech_debt 索引（docs/tech_debt.md）

| 编号 | 状态 | 摘要 |
|---|---|---|
| FULL-001 | 已关闭 | 批次 1 新模板 fail（模式 A/B），已修 |
| FULL-002 | 已修复 | 中文序号后缀导致匹配失败，fuzzy fallback |
| FULL-003 | 已修复 | `（已修复）` 状态后缀，fuzzy fallback |
| FULL-004 | 待评估 | 中文序号承担实例区分，strip 后 instance_index 配对失败 |
| FULL-005 | 待评估 | 大小写 / 同义词 / 字形差异 |
| FULL-006 | 已修复 | 市监局标题混入阿拉伯序号、等级括号、多处前缀 |
| FULL-007 | 待评估 | 跨轮次父报告查找失败（10 条 none） |
| FULL-008 | 已记录 | none 根因分布；Locator 修复后新增 9 条的逐条归类 |
| FULL-009 | 待评估 | 回归报告条目重名（p3）与状态文本丢失（p2） |
| FULL-010 | 待评估 | 摘要计数按接口数而非漏洞条数（口径差异） |

## 关键文件

- `data/full_batch.json`：363 份原始批次划分（1 = 200 渗透，2 = 163）
- `data/full_batch_2a1/2a2/2a3/2b/2c.json`：批次 2 的五段切分
- `data/run_segment_incremental.py`：分段执行驱动（逐份解析后立即入库），不改项目源码
- `data/full_batch_1_status_final.json`：**批次 1 的唯一权威最终状态**
  - `data/full_batch_1_status.json` 为 `run_full_batch.py` 临时输出（硬编码文件名），**不要依赖**
  - 历史归档：`full_batch_1_status_initial.json`、`full_batch_2a_status_partial.json`
- `data/full_batch_2a1/2a2/2a3/2b/2c_status.json`：各段执行明细
- `data/backup_stale_3/`：3 份过期缓存的原始产物
- `data/_vuln_backup_before_*.db`：回填前的数据库备份

## ChatBI 全量库验收 · 2026-11-15

### chat_eval（18 条）
- PASS 18 / FAIL 0 = 100%（门禁 90%，稳定）

### image_eval（10 条）
- PASS 9 / FAIL 1 = 90%（门禁 80%，达标）
- 波动范围：8/10 – 9/10（3 次实测：8/10、9/10、9/10）
- 唯一稳定失败：`IMG-C03`（`[IMG-006]`，同一报告 16 张同名截图，注入图排第 11 位被 limit 截断）
- 已知抖动：`IMG-003` / `IMG-C02` 偶尔失败，原因是 LLM 未声明"以原图为准"或漏引一个 OCR 字段名，重跑可恢复

### 本轮修复
- `[AGENT-003]` `_wrap_tool` 重建 FunctionTool 时丢失原 schema，已修 + 补单测（`tests/test_wrap_tool.py`）
- 75 条 `v_vulnerability.source_file` 缺轮次前缀，已对齐 `v_report.report_name`（备份 `data/_vuln_backup_before_source_file_fix.db`）
- `[IMG-005]` `search_image_evidence` 增加 `source_file` 参数（部分修复）
- `_check_image` 增加去空格归一化，OCR 原文 `event Id` 与 Agent 输出 `eventId` 视为同一词
- IMG-005 问题范围从"整个团队"收窄到"单个报告"，修复语义矛盾
- IMG-C03/C04 的注入图片重新入库（2 行，`image_path` 改为 `*_injected.png`，OCR 前置注入文本），FTS 已 `rebuild`

### E-LOAD 复验（数据修复后）
8 项指标：001/004/005/006/007 达标，002 良好 0.9782，003 良好 0.8702，008 = 1240 → **通过**

### 待评估
- `[IMG-006]` 同一报告多张同名截图时的截断问题
- `[FULL-007]` 跨轮次父报告查找（10 条 none）
- 21 份 `pending_review` 人工核对（5 份已诊断结案）

## 下一步

1. **人工核对 16 份 `pending_review`**（5 份已诊断结案，见上表）
2. `[FULL-007]` 跨轮次父报告查找（影响 10 条 none，占比最大）
3. `[FULL-004]` 父报告 `instance_index` 建模缺陷（影响新增 9 条中的 6 条）
4. `[FULL-010]` 评估是否放宽 `count_cross_check` 对回归报告的口径，减少 pending 误报
5. ~~全量验收：按 `docs/04_evaluation.md` 的 E-LOAD 指标（含新增 E-LOAD-008 漏洞总量 ≥ 1200）~~ **已完成 2026-11-15**
