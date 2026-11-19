# ChatBI-Vuln 项目 · 技术选型退路（Fallback Plan）

> **文档定位**：每个关键选型都押了一个注。本文档记录"押错了怎么办"——失败信号、退路、切换成本、切换流程。
>
> **使用方式**：当某个模块的表现低于门禁线且短时间无法修复时，先查本文档判断"是不是选型问题"，再决定是否切换。

---

## 1. 为什么需要退路

技术选型在两种情况下会出错：

1. **押注时信息不足**：选型时没有真实数据，事后发现不合用；
2. **选型后环境变化**：依赖库重大升级、模型能力变化、报告格式演进。

**没有退路的选型是赌博**。本文档不阻止选型，只确保"押错时能改"，且改动成本可预估。

---

## 2. 选型退路清单

| # | 选型 | 失败信号 | 退路 | 切换成本 | 切换触发条件 |
|---|---|---|---|---|---|
| F-01 | MinerU 作主 Adapter | E-PARSE-001 < 0.85，且抽检显示表格召回不足 | pdfplumber | 中（换 Adapter 实现，重跑 Phase 2） | E-PARSE-001 未达门禁线且 MinerU 版本更新后仍未改善 |
| F-02 | PaddleOCR 作 OCR 引擎 | E-PARSE-006 < 0.80，中文识别错误率高 | Tesseract + chi_sim | 低（改 `image_rules.yaml` 的 `ocr.engine`） | 同上 |
| F-03 | gpt-4o-mini 作 Agent 模型 | E-CHAT-001 < 0.85，或 E-CHAT-003 < 0.85 | gpt-4o / claude-sonnet | 低（改一行 model 名） | 连续 2 次评测未达门禁线 |
| F-04 | trigram 分词器 | 建库时报 `no such tokenizer`，或 E-CHAT-004 < 0.70 | unicode61 | 低（改 `schema.sql` 的 `tokenize`） | SQLite 版本 < 3.34，或 trigram 召回显著劣于预期 |
| F-05 | pdfplumber 作 fallback Adapter | 主 Adapter 失败时，fallback 也失败 | 直接标 `parse_status=fail`，人工处理 | 无（不切换） | 不适用（无备选） |
| F-06 | SQLite 作存储 | 单库 > 5 GB，或并发查询性能不足 | DuckDB / PostgreSQL | 高（schema 迁移、连接层重写） | MVP 阶段不触发；长期数据量达万份报告时评估 |
| F-07 | 图片存文件系统 | 图片数量 > 10 万，文件系统 inode 耗尽 | 对象存储（MinIO/S3） | 中（改 `image_extractor.py` 与 `search_image_evidence.py`） | 图片数量超过文件系统推荐上限 |
| F-08 | OpenAI Agents SDK | SDK 停止维护，或 API 重大变更 | LangChain Agents / 自研编排 | 高（重写 `app/agent/` 与 `app/tools/`） | 官方宣布停止维护，或安全漏洞 |
| F-09 | 单 Agent 架构 | 出现明显异构的查询需求，单 Agent 处理混乱 | 多 Agent + Handoff | 中（拆分 tools、增加路由） | Agent 回答的"牛头不对马嘴"率 > 10% |

---

## 3. 每个退路的切换流程

### F-01 · MinerU → pdfplumber

**判断是否该切换**：

```bash
# 1. 跑一次评测
python tests/eval/eval_parse.py

# 2. 若 E-PARSE-001 < 0.85，检查失败报告的 common pattern
grep "召回率" tests/eval/reports/latest.md

# 3. 检查 MinerU 是否有新版本修复
pip index versions mineru
```

**若确定切换**：

1. 在 `corpus_profile.json` 中改 `parse_strategy.primary_adapter = "pdfplumber"`；
2. 在 `config/pipeline_version.txt` 递增版本号；
3. 重跑 Phase 2（全量），耗时约 5–15 分钟 / 50 份报告（不含 OCR）；
4. 重跑评测，确认 E-PARSE-001 改善；
5. 在 `05_decisions.md` 追加决策记录：`D-XXX · 切换 MinerU 到 pdfplumber`。

**代价**：
- pdfplumber 对复杂排版（多栏、图文混排）的表格召回不如 MinerU；
- 需要重写 `pdfplumber_adapter.py` 的跨页合并逻辑（参考 P-PDF-005）；
- 若报告中大量扫描件，pdfplumber 返回空文本（P-PDF-004），需依赖 OCR 兜底。

**建议**：切换前先做小范围测试（3–5 份报告），确认召回率改善明显再全量切换。

---

### F-02 · PaddleOCR → Tesseract

**判断是否该切换**：

```bash
# 1. 单独跑 OCR 评测
python tests/eval/eval_ocr.py --sample 20

# 2. 检查识别错误
cat tests/eval/reports/ocr_detail.md
# 若中文错误率 > 30%，考虑切换
```

**若确定切换**：

1. 在 `config/image_rules.yaml` 中改 `ocr.engine: tesseract`；
2. 递增 `pipeline_version`；
3. 重跑 Phase 2（只重跑图片提取，表格可复用）；
4. 重跑 E-PARSE-006。

**代价**：
- Tesseract 对中英文混排的识别不如 PaddleOCR；
- 需要安装 `tesseract-ocr` 与 `tesseract-ocr-chi-sim`；
- OCR 速度可能下降 30%–50%。

**建议**：仅在 PaddleOCR 完全不可用（如平台不支持、依赖冲突无法解决）时切换。若只是识别率略低，优先考虑换 PaddleOCR 的模型版本，而非换引擎。

---

### F-03 · gpt-4o-mini → gpt-4o

**判断是否该切换**：

```bash
# 1. 跑 chat_eval
python tests/eval/eval_chat.py

# 2. 若 E-CHAT-001 或 E-CHAT-003 < 0.85，检查失败用例
cat tests/eval/reports/latest.md | grep "CHAT-"
```

**若确定切换**：

1. 在 `app/agent/definition.py` 中改 `model="gpt-4o"`；
2. 在 `config/pipeline_version.txt` 递增版本号（Agent 行为变了）；
3. 重跑 Phase 4 评测。

**代价**：
- 成本上涨约 10–20 倍（gpt-4o-mini vs gpt-4o）；
- 响应时间增加；
- 对于简单统计问题，可能"过度思考"。

**建议**：
- 先用 `search_knowledge` 覆盖高频问题，减少对 LLM 生成的依赖；
- 仅在生成路径的错误率确实低于门禁线时切换；
- 可考虑混合策略：知识库未命中时用 gpt-4o，命中时仍用 gpt-4o-mini（但增加路由复杂度）。

---

### F-04 · trigram → unicode61

**判断是否该切换**：

```bash
# 检查 SQLite 版本
python -c "import sqlite3; print(sqlite3.sqlite_version)"
# < 3.34 必须切换
```

**若确定切换**：

1. 在 `app/db/schema.sql` 中改 `tokenize='unicode61'`；
2. 重建 FTS 表（`DROP TABLE v_image_evidence_fts;` 然后重建）；
3. 执行 `INSERT INTO v_image_evidence_fts(v_image_evidence_fts) VALUES('rebuild');`；
4. 重跑 E-CHAT-004（图片证据检索）。

**代价**：
- 中文检索按单字切分，召回率显著下降（可能从 0.90 降到 0.60）；
- 对 payload、URL 等碎片化文本的检索效果差。

**建议**：
- 优先升级 SQLite 版本，而不是降级分词器；
- 若必须降级，考虑在 `search_image_evidence` 中增加 LIKE 兜底。

---

### F-06 · SQLite → DuckDB / PostgreSQL

**触发条件**（MVP 阶段不触发）：
- 单库 > 5 GB；
- 单表 > 100 万行；
- 多用户并发写（MVP 不支持，不在考虑范围）。

**切换成本高**：
- `schema.sql` 需迁移（SQLite 的 `INTEGER PRIMARY KEY AUTOINCREMENT` 在 PG 中改 `SERIAL`）；
- `execute_sql` 的只读校验逻辑需适配（PG 的 `EXPLAIN` 校验方式不同）；
- `search_image_evidence` 的 FTS5 需改为 PG 的 `tsvector` 或 DuckDB 的全文索引。

**MVP 结论**：不切换。若未来需要，另开技术设计。

---

### F-08 · OpenAI Agents SDK → 其他

**触发条件**：
- SDK 停止维护；
- 官方宣布 breaking change 且迁移成本高于自研。

**切换成本高**：
- `app/agent/definition.py` 重写（Agent 定义、instructions、tools 绑定）；
- `app/tools/*.py` 的 Function Schema 格式适配；
- Session 管理重写（`SQLiteSession` 是 SDK 特有）。

**建议**：
- 若必须切换，优先考虑 `openai` 官方 SDK 直接调 API + 自研轻量编排（比引入 LangChain 更可控）；
- 保持 `app/tools/` 与 `app/agent/` 的边界清晰（03 C-DEP-002），降低切换成本。

---

## 4. 切换流程模板

任何选型切换都按以下流程：

```
1. 判断阶段
   ├─ 是否已通过门禁？→ 若已通过，不得切换（不得为了"更好"而冒风险）
   └─ 未通过门禁 → 继续
2. 判断根因
   ├─ 是选型问题？→ 继续
   └─ 是代码 bug？→ 修复代码，不切换
3. 小范围测试
   ├─ 选 3–5 份代表性报告
   └─ 对比新旧方案的关键指标
4. 决定切换
   ├─ 改善明显（如召回率 +15%）→ 切换
   ├─ 改善微小（如 +2%）→ 不切换
   └─ 变差 → 不切换
5. 执行切换
   ├─ 改配置/代码
   ├─ 递增 pipeline_version
   ├─ 重跑评测
   └─ 在 05_decisions.md 记录决策
6. 观察
   └─ 连续 2 次评测达标后视为切换稳定
```

**关键原则**：**不得为了"技术上新"而切换**。若当前方案达标，即使新方案理论上更好，也不切换。

---

## 5. 不切换的情况（明确记录，避免反复讨论）

| 项 | 不切换的原因 |
|---|---|
| 图片存 BLOB | D-005 已决策；存文件系统的优势明显 |
| 用 LLM 做解析 | D-002 已决策；可重复性与隐私要求排除了这条路 |
| 启用 VLM 图片描述 | D-004 已决策；幻觉风险不可接受 |
| 多 Agent 架构 | D-006 已决策；MVP 场景不需要 |
| 立即物理删除孤儿 | D-015 已决策；风险高于收益 |

**若有人提议推翻以上决策**，必须先在 `05_decisions.md` 中给出"推翻条件"已满足的证据，否则不讨论。

---

## 6. 退路与门禁的关系

- **退路不是"达标失败就切换"**。切换本身有成本，且新方案也可能不达标。
- **退路是"在特定失败信号下，有可预见的下一步"**，而不是"随意换"。
- **门禁线不可豁免**（D-012），但"用哪条路径达门禁线"可以选。

例如：E-PARSE-001 < 0.85 时：
- **不应**：修改 `pipeline_eval.csv` 的 `expected_vuln_count` 让指标"看起来达标"；
- **应**：判断是 MinerU 的问题还是 Extractor 的问题；若是 MinerU，按 F-01 切换；若是 Extractor，修 Extractor 的代码。

---

## 附录 · 失败信号速查

| 指标 | 门禁线 | 失败时的第一步 |
|---|---|---|
| E-PARSE-001（召回率） | 0.85 | 查 `precision_{tag}.csv` 找 common pattern；若表格型报告普遍召回低 → F-01 |
| E-PARSE-006（OCR 成功率） | 0.90 | 抽检 20 张图片；若中文错误多 → F-02 |
| E-CHAT-001（统计正确率） | 0.90 | 看失败用例的 SQL 是否生成错误；若是 → 先扩 `kb_entry`，再考虑 F-03 |
| E-CHAT-004（图片检索命中率） | 0.80 | 检查 FTS5 是否可用；若不可用 → F-04 |
| E-E2E-002（全量初始化耗时） | ≤ 30min / 50 份 | 先优化解析并发；若仍不达标 → 评估 F-06 |