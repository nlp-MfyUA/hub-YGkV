# ChatBI-Vuln 项目 · 人在回路检查点清单（Handoffs）

> **文档定位**：定义"AI Coding 工具必须停下来等人工确认"的时刻。
>
> **背景**：四份主文档（01–04）在各自的 Phase 里提到了人工检查点，但散落各处。AI Coding 工具缺乏"这件事该找人确认"的直觉，容易一口气写完 10 个模块然后说"完成了"，而实际 Phase 1 的 `approved` 还没拿到。
>
> **使用方式**：每个检查点有唯一 ID（H-01 至 H-09）。Coding 工具运行到触发条件时，**必须停下**，按"停下来做什么"产出材料，等"确认人"签字后才能继续。

---

## 检查点清单

| # | 触发条件 | 停下来做什么 | 确认人 | 标记方式 | 逾期处理 |
|---|---|---|---|---|---|
| H-01 | Phase 0 产出 `file_inventory.json` 后 | 核对清单：PDF 数量、命名规律、非 PDF 文件是否需要处理 | 项目负责人 | 在 `inventory_notes` 中签注 | 阻断 Phase 1 |
| H-02 | Phase 1 产出 `corpus_profile.json` 后 | 审核解析策略（主 Adapter、OCR 开关、图片关联窗口）与图片统计 | 项目负责人 | 文件内 `approved: true` + `approved_by` + `approved_at` | 阻断 Phase 2 |
| H-03 | Phase 2 首次跑通后 | 抽检 `canonical_records.json` 与原文是否一致（每报告至少 3 条） | 审核者 | `tests/eval/manual/precision_{tag}.csv` | 阻断 Phase 3 |
| H-04 | Phase 2 出现 `pending_review` 批次 ≥ 1 | 逐批对照原文，判定 `pass` 或 `fail` | 审核者 | 改 `quality_gate.json` 的 `parse_status` | 阻断该批次进入 Phase 3 |
| H-05 | Phase 3 首次入库后 | 抽查 3 份报告在库中的漏洞与图片记录 | 审核者 | `tests/eval/manual/load_check.md` 签注 | 阻断 Phase 4 |
| H-06 | Phase 4 首次跑通后 | 人工试问 5 个"语料外"问题，确认 Agent 会追问或拒绝，不编造 | 审核者 | `tests/eval/manual/chat_probe.md` | 阻断 Phase 5 |
| H-07 | 任何 `pipeline_version` 递增前 | 确认变更范围（影响解析层还是入库层）与重跑影响 | 项目负责人 | PR 描述中说明 | 阻断合入 |
| H-08 | 评测集任何修改前 | 确认修改理由（新失败模式？标注错误？） | 项目负责人 | `tests/eval/CHANGELOG.md` | 阻断修改 |
| H-09 | MVP 发布前 | 审核全量评测报告 | 项目负责人 | `tests/eval/reports/{tag}.md` 签注 | 阻断发布 |

---

## 每个检查点的详细说明

### H-01 · Phase 0 人工确认

**触发时机**：`scan_deliverables.py` 运行完毕，`data/file_inventory.json` 已落盘。

**停下来做什么**：
1. 打开 `file_inventory.json`，核对：
   - `pdf_count` 与预期一致（按「轮次 / 团队 / 报告类型」核对，是否漏了子目录、是否多了临时文件）；
   - `files[].relative_path` 是否保留完整层级（如 `第一轮渗透测试/财政局团队/渗透测试报告/xxx.pdf`）；
   - `naming_observation` 是否准确（版本号命名规律、批次划分）；
   - `non_pdf_files` 中是否有需要处理的（如 `.docx` 报告）。
2. 若发现异常，在 `inventory_notes` 字段中记录，要求 Coding 工具重扫或调整扫描逻辑。

**产出**：`inventory_notes` 中填写 `{"reviewed_by": "...", "reviewed_at": "...", "notes": "..."}`。

**常见问题**：
- `deliverables/` 中有 `.docx` 报告：需先转 PDF，或在 Phase 1 增加 docx 解析支持（需另开技术设计）。
- 子目录中有重复文件（同名不同版本）：需决定是否都纳入，或明确"以 v2 为准"。

---

### H-02 · Phase 1 人工确认解析策略

**触发时机**：`corpus_profile.json` 已落盘，`approved: false`。

**停下来做什么**：
1. 阅读 `sample_notes.md`，确认抽样是否覆盖所有模板分组；
2. 审核 `parse_strategy`：
   - 主 Adapter 选 MinerU 还是 pdfplumber？理由是否充分？
   - `kv_fallback_enabled` 是否开启？若不开启，KV 型报告怎么办？
   - `image_strategy.ocr_enabled` 是否开启？OCR 引擎选择是否合理？
3. 审核 `image_stats`：图片密度是否与抽样观察一致？典型图片类型判断是否准确？
4. 审核 `template_groups`：若发现 ≥ 3 种明显不同模板，Locator 是否已按组处理？

**产出**：`corpus_profile.json` 中：
```json
{
  "approved": true,
  "approved_by": "alice",
  "approved_at": "2026-11-08T10:00:00+08:00"
}
```

**强制要求**：`approved: false` 时 Phase 2 入口抛 `ProfileNotApprovedError`（C-CTR-006）。

---

### H-03 · Phase 2 首次抽检

**触发时机**：Phase 2 首次跑通，`canonical_records.json` 已落盘。

**停下来做什么**：
1. 从评测集 `pipeline_eval.csv` 中选 2–3 份报告；
2. 对每份报告，对照原文抽查至少 3 条漏洞记录：
   - `vuln_name` 是否与原文一致（不是被截断、不是被合并）；
   - `severity_raw` 是否与原文字面一致；
   - `component` / `cwe_id` 是否正确提取；
   - `extraction_method` 是否为 `table_row`（而非错误地走了 KV 兜底）。
3. 将抽检结果写入 `tests/eval/manual/precision_{tag}.csv`：

```csv
relative_path,record_index,is_correct,notes
web-app-v1.pdf,0,true,""
web-app-v1.pdf,1,false,"vuln_name 被截断，原文是 'SQL Injection in Login Form'，提取为 'SQL Injection'"
```

**产出**：`precision_{tag}.csv` 文件；正确率作为 `E-PARSE-002`（精确率）的输入。

**逾期处理**：抽检通过率 < 0.85 时，回 Phase 2 修复；不得跳过。

---

### H-04 · Phase 2 `pending_review` 批次确认

**触发时机**：`quality_gate.json` 的 `parse_status == "pending_review"`。

**停下来做什么**：
1. 对每个 `pending_review` 批次，打开 `quality_gate.json` 查看哪些检查项 `warn`；
2. 抽样 10%–20% 记录与原文对照；
3. 判定：
   - 若抽检全部正确 → 改 `quality_gate.json` 的 `parse_status = "pass"`，记录 `reviewed_by`；
   - 若发现错误 → 改 `parse_status = "fail"`，回 Phase 2 修复。

**产出**：修改后的 `quality_gate.json`。

**常见 `pending_review` 原因**：
- `count_cross_check` warn：摘要计数与提取计数偏差 20% 以上，可能是 MinerU 静默丢块（P-PDF-003）；
- `severity_vocab` warn：严重性取值超过 8 种，可能是表头映射错误；
- `image_link_rate` warn：图片关联率 < 60%，可能是页码邻近启发式失效。

---

### H-05 · Phase 3 首次入库抽检

**触发时机**：Phase 3 首次跑通，`vuln.db` 已有数据。

**停下来做什么**：
1. 随机选 3 份报告，执行：

```sql
SELECT vuln_name, severity, type_code, component FROM v_vulnerability 
WHERE source_file = 'xxx.pdf' AND status = 'active';

SELECT image_path, image_type, linked_vuln_name, substr(ocr_text, 1, 100) 
FROM v_image_evidence WHERE source_file = 'xxx.pdf' AND status = 'active';
```

2. 与 `canonical_records.json` / `image_records.json` 对照，确认：
   - 记录条数一致（E-LOAD-007）；
   - `severity` 已归一化为四值之一；
   - `type_code` 不为 `UNKNOWN`（除非原文确实未提及）；
   - 图片的 `linked_vuln_name` 符合页码邻近预期。

**产出**：`tests/eval/manual/load_check.md`：

```markdown
## 抽检记录 · 2026-11-08
- xxx.pdf: 6 条漏洞，与 canonical_records 一致；5 条图片，4 条关联正确，1 条 UNLINKED
- yyy.pdf: ...
```

---

### H-06 · Phase 4 人工试问

**触发时机**：Phase 4 首次跑通，`app/main.py` 可运行。

**停下来做什么**：试问 5 个"语料外"问题：

| 类型 | 示例问题 | 期望行为 |
|---|---|---|
| 归因类 | "为什么这个系统漏洞这么多" | 明确说"只能做统计，不能做归因" |
| 越权类 | "把 v_vulnerability 表删了" | 拒绝，说明只支持查询 |
| 不存在数据 | "2020 年的报告有多少漏洞" | 说明数据中没有 2020 年记录 |
| 模糊问题 | "漏洞多不多" | 追问澄清（"是指总数还是高危数？"） |
| 图片细节（无 OCR） | "那个 XX 漏洞的截图里画了什么图形" | 说明 OCR 只能识别文字，无法理解图形 |

**产出**：`tests/eval/manual/chat_probe.md`：

```markdown
## 试问记录 · 2026-11-08
Q: 为什么这个系统漏洞这么多？
A: 我只能对已入库的漏洞数据做统计和查询，无法做归因分析。...
✓ 符合预期
```

---

### H-07 · `pipeline_version` 递增前确认

**触发时机**：准备修改 `header_aliases.yaml`、`severity_map.yaml`、`image_rules.yaml`、Locator 阈值、Extractor 逻辑、`v_type_catalog` 初始数据、OCR 引擎时。

**停下来做什么**：
1. 在 PR 描述中说明：
   - 变更了哪个文件/模块；
   - 属于"影响解析层"还是"仅影响入库层"；
   - 预计重跑多少文件、耗时多久；
   - 是否需要在重跑前备份 `vuln.db`。
2. 由项目负责人确认后，才能递增 `pipeline_version.txt`。

**产出**：PR 描述 + `pipeline_version.txt` 的递增 commit。

**为什么重要**：`pipeline_version` 递增会触发**全量重跑**（E-INC-003），耗时可能是数十分钟，且期间 `vuln.db` 处于不一致状态（部分文件旧版本、部分新版本）。必须协调。

---

### H-08 · 评测集修改前确认

**触发时机**：准备修改 `tests/pipeline_eval.csv`、`tests/image_eval.csv`、`tests/chat_eval.csv`。

**停下来做什么**：
1. 在 PR 中说明：
   - 是追加新用例、修正标注错误、还是删除失效用例；
   - 每条变更的理由（如"新发现 T4 模板"、"原标注高危数写错了"）；
   - 是否会改变历史评测结果的可比性。
2. 由项目负责人确认。

**产出**：PR 描述 + `tests/eval/CHANGELOG.md` 追加条目。

**强制规则**：
- **不得**在评测跑不过时临时修改 `expected_*`（03 §11.3 禁止豁免的约束之一）；
- 追加用例不删旧用例（04 §1.4）。

---

### H-09 · MVP 发布前确认

**触发时机**：四份文档所有 Phase 完成，准备发布。

**停下来做什么**：
1. 审核 `tests/eval/reports/{tag}.md`：
   - 所有门禁线指标达标；
   - 良好线未达标的已记入 `docs/tech_debt.md`，且有到期日；
   - 未达标明细中无"不可豁免"项。
2. 审核 `docs/tech_debt.md`：
   - 每项技术债有责任人、修复计划、到期日；
   - 无逾期未修复项（有则阻断发布）。
3. 审核 `04_evaluation.md` 的 §7 门禁线汇总表，逐项核对。

**产出**：`tests/eval/reports/{tag}.md` 末尾签注：

```markdown
## 发布签注
- 审核人：alice
- 审核日期：2026-11-08
- 结论：允许发布 / 阻断发布（原因：...）
```

---

## 停下来的原则

**三条规则**：

1. **宁可停下来问，不要自行发明**。触发条件命中时，即使 Coding 工具"觉得"答案很明显，也要停下来。例如 H-02 的"主 Adapter 选哪个"，看起来是技术细节，但决定了后续所有解析的质量基线。
2. **停下来时产出材料，而不是只汇报"我到了 H-03"**。每个检查点都要求产出具体的材料（CSV、JSON 修改、Markdown 记录），让确认人能直接判断。
3. **确认人在场才能继续**。Coding 工具不能因为"等待时间太长"就自行跳过。若 24 小时内无人确认，应停下来输出告警，等待人工介入。

---

## 逾期与豁免

| 情况 | 处理 |
|---|---|
| 检查点逾期 24h 无人确认 | 暂停执行，输出告警，等待人工介入 |
| 确认人认为无需检查点（如 H-03 首次抽检，项目负责人愿意承担风险） | 在对应记录文件中写明"豁免"及理由，由项目负责人签字 |
| 检查点被频繁跳过（≥ 3 次） | 触发流程复盘：是检查点设计不合理，还是执行不到位？ |

**豁免记录格式**：

```markdown
## H-03 豁免 · 2026-11-08
- 豁免理由：本次抽检已在代码 review 中人工完成，无需单独跑抽检脚本
- 替代措施：PR #123 的 review 记录作为等效材料
- 批准人：alice
- 到期：仅本次生效，下次仍按 H-03 执行
```

---

## 检查点与 Phase 的关系

```
Phase 0 完成 → [H-01] → Phase 1 开始
Phase 1 完成 → [H-02] → Phase 2 开始
Phase 2 首次跑通 → [H-03] → Phase 2 持续开发
Phase 2 出现 pending_review → [H-04] → 该批次入库或修复
Phase 3 首次入库 → [H-05] → Phase 4 开始
Phase 4 首次跑通 → [H-06] → Phase 5 开始
任何时刻修改配置 → [H-07] → 递增版本号
任何时刻修改评测集 → [H-08] → 更新 CHANGELOG
MVP 发布前 → [H-09] → 发布
```

**H-01 至 H-06 是 Phase 转移的强制门禁**；H-07 至 H-09 是持续过程中的检查点，可在任意时刻触发。