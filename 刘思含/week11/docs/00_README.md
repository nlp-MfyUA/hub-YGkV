# ChatBI-Vuln 项目 · 入口文档（README）

> **一句话定位**：把渗透测试报告 PDF（含表格、正文、图片证据）转换为 SQLite 中的结构化漏洞数据，再通过 OpenAI Agents SDK 构建的对话式 Agent 完成统计、图表与漏洞细节问答。
>
> **本文件是新读者（人或 AI Coding 工具）的第一个入口**。它不重复任何设计细节，只回答三个问题：文档怎么读、项目怎么跑、遇到不确定时去哪找答案。

---

## 1. 文档地图

| 编号 | 文件 | 定位 | 读者 |
|---|---|---|---|
| 01 | `01_master_workflow.md` | 总纲：六个 Phase、目录结构、阶段契约、门禁 | 所有人 |
| 02 | `02_technical_design.md` | 技术设计：数据结构、函数签名、SQL、Agent 提示词 | 实现者 |
| 03 | `03_constraints.md` | 约束：什么不许做、什么必须做、CI 判定 | 实现者 + 审核者 |
| 04 | `04_evaluation.md` | 评分：评测集设计、量化指标、门禁线 | 审核者 + 项目负责人 |
| 05 | `05_decisions.md` | 决策记录：关键设计选择的理由与被否决的替代方案 | 所有人 |
| 06 | `06_pitfalls.md` | 陷阱清单：已知的、一试就错的地方 | 实现者 |
| 07 | `07_fixtures.md` | 测试夹具：合成的最小可复现测试数据 | 实现者 |
| 08 | `08_handoffs.md` | 检查点：必须停下来等人工确认的时刻 | 实现者 + 项目负责人 |
| 09 | `09_fallback_plan.md` | 退路：技术选型押错注时的切换方案 | 项目负责人 |
| 10 | `10_environment.md` | 环境：安装步骤、版本要求、首跑验证 | 实现者 |
| — | `schemas/` | 可执行契约：JSON Schema 与 CSV 列定义 | 实现者 |

---

## 2. 阅读顺序

### 2.1 首次上手（完整读一遍）

```
00_README（本文件）
  → 01_master_workflow（理解 Phase 划分与门禁）
  → 02_technical_design（理解每个模块怎么实现）
  → 03_constraints（理解边界）
  → 04_evaluation（理解怎么算好）
  → 05_decisions + 06_pitfalls（实现前必读）
  → 07_fixtures + 10_environment（开工前必读）
  → 08_handoffs（了解何时停下来问人）
```

### 2.2 按 Phase 的最小必读集

**不要每次重读全部文档**。开工某个 Phase 前，只读下列最小集：

| Phase | 必读 | 选读 |
|---|---|---|
| Phase 0 | 01 §Phase 0、02 §3、03 §1 | — |
| Phase 1 | 01 §Phase 1、02 §4、03 §1.2 | 06 的 pdfplumber 条 |
| Phase 2 | 01 §Phase 2、02 §5、03 §CTR+IMG 域、06 全部 | 05 的 D-001/004/010/011 |
| Phase 3 | 01 §Phase 3、02 §6、03 §RO+CTR 域、06 的 SQLite/FTS5 条 | 05 的 D-007/008 |
| Phase 4 | 01 §Phase 4、02 §7、03 §RO+IMG+SEC 域、06 的 Agents SDK/Session 条 | 05 的 D-006/009 |
| Phase 5 | 01 §Phase 5、02 §8、03 §VER 域、06 的增量相关条 | 05 的 D-003/014/015 |

**如果时间紧，任何 Phase 的最低限度**是读 `01` 对应 Phase + `02` 对应章节 + `06` 中该 Phase 出现的陷阱。跳过这些大概率会踩坑。

---

## 3. 项目当前状态

| 文档 | 版本 | 状态 |
|---|---|---|
| 01_master_workflow | v1.1 | 已确认 |
| 02_technical_design | v1.1 | 已确认 |
| 03_constraints | v1.0 | 已确认 |
| 04_evaluation | v1.0 | 已确认 |
| 05_decisions | v1.0 | 已确认 |
| 06_pitfalls | v1.0 | 已确认 |
| 07_fixtures | v1.0 | 已确认 |
| 08_handoffs | v1.0 | 已确认 |
| 09_fallback_plan | v1.0 | 已确认 |
| 10_environment | v1.0 | 已确认 |

**当前未决问题**（详见 01 §6）：
- `deliverables/` 是否包含扫描件：需在 Phase 1 统计后决定是否启用 OCR 对扫描件页的额外处理
- 跨报告漏洞去重：MVP 不做，留作扩展

**当前不允许做的事**（详见 03 §11.3 不可豁免清单）：
- 启用 VLM 图片语义描述（C-IMG-001）
- 让 `execute_sql` 接触白名单外的表（C-RO-005）
- 让 `app/` 以可写模式打开 `vuln.db`（C-RO-001）
- 把报告内容发送到外部服务（C-SEC-001）

---

## 4. 首跑命令序列（Phase 0 之前）

**目标**：在 15 分钟内确认环境可用、依赖齐备、数据库结构正确。

```bash
# 1. 环境准备（详见 10_environment.md）
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 校验 SQLite 版本与 FTS5 支持
python -c "import sqlite3; print(sqlite3.sqlite_version); \
           print(sqlite3.connect(':memory:').execute(\"SELECT sqlite_compileoption_used('ENABLE_FTS5')\").fetchone())"
# 期望：版本 ≥ 3.34，FTS5 输出 (1,)

# 3. 建库
mkdir -p app/db
sqlite3 app/db/vuln.db < app/db/schema.sql

# 4. 验证 schema（关键约束 C-RO-005、C-RO-006、C-IMG-002）
sqlite3 app/db/vuln.db ".tables"
# 期望：kb_entry pdf_index v_image_evidence v_image_evidence_fts ...

sqlite3 app/db/vuln.db "SELECT COUNT(*) FROM v_type_catalog;"
# 期望：10

# 5. 生成测试夹具（07_fixtures.md）
python tests/fixtures/build_fixtures.py
ls tests/fixtures/pdfs/
# 期望：simple_table.pdf  no_table.pdf  table_with_image.pdf

# 6. 跑一次约束测试
pytest tests/test_dependency_boundary.py -v
# 期望：全部 PASS（此时 app/ 和 pipeline/ 应还是空骨架）
```

**若任一步失败**，查 `10_environment.md` 的"常见安装问题"，或 `06_pitfalls.md` 的对应条。**不要跳过这一步直接开始写代码**。

---

## 5. 遇到问题去哪找

| 问题类型 | 去哪找 |
|---|---|
| "这个设计为什么这样？" | `05_decisions.md` |
| "我改了这条会不会违反约束？" | `03_constraints.md` 对应约束域 |
| "报错了，可能是已知坑" | `06_pitfalls.md` 对应模块 |
| "怎么写单测？" | `07_fixtures.md` |
| "这个 Phase 什么时候算完成？" | `04_evaluation.md` 的 §7 门禁线汇总表 |
| "我应该停下来问人吗？" | `08_handoffs.md` |
| "选的库不好用，能换吗？" | `09_fallback_plan.md` |
| "某个数据结构字段名是什么？" | `02_technical_design.md` §1 或 `schemas/` |
| "装不上了" | `10_environment.md` |

**如果以上都没答案**：说明四份主文档 + 五份补充文档存在空白。此时 Coding 工具应：
1. **停下来**，不要自行发明；
2. 在 PR 或 Issue 中记录"文档空白点"；
3. 由项目负责人决定是补充文档还是调整设计。

---

## 6. 给 AI Coding 工具的三条硬规则

1. **顺序执行，不跳 Phase**。每个 Phase 有明确门禁，前置 Phase 未通过不得开始下一 Phase。
2. **每完成一个 Phase 停下来汇报**。汇报格式："Phase N 完成，产物在 X，门禁自检为 pass，请确认是否继续"。参见 `08_handoffs.md` 的 H-01 至 H-09。
3. **禁止"善意优化"**。看到某处可"做得更好"时，先查 `05_decisions.md` 是否已经拒绝过这个方向；若是，则不改；若不是，停下来问人，不要直接改。

---

## 7. 文档之间的强制一致性

以下条目在四份主文档 + 补充文档中必须保持一致，任一处改动都需同步全链路：

| 一致性项 | 出现位置 |
|---|---|
| `CanonicalVulnRecord` 字段名 | 01 §Phase 2、02 §1.1、03 C-CTR-012、schemas/ |
| `ImageRecord` 字段名 | 01 §Phase 2、02 §1.2、03 C-CTR-012、schemas/ |
| `severity` 四值枚举 | 01、02 §2、03 C-CTR-008、04 E-LOAD-002 |
| 表名白名单（五张） | 02 §7.2.3、03 C-RO-005 |
| `pipeline_version` 递增触发条件 | 02 §9.4、03 C-VER-002、05 D-015 |
| 图片 OCR 成功率门禁 0.90 | 01 §Phase 2、04 E-PARSE-006 |
| 图片关联率门禁 0.60 | 01 §Phase 2、04 E-PARSE-007 |

**改动流程**：任何一处的改动，在 PR 中必须同时更新上述所有出现位置，否则 CI 的一致性检查（`tests/test_consistency.py`）阻断合入。