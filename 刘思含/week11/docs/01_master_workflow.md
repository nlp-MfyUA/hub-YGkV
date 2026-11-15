# ChatBI-Vuln 项目 · 总体工作流框架（Master Workflow）

> **文档定位**：这是项目的**总纲**，定义"做什么、按什么顺序做、每个阶段的输入输出和验收门禁"。
> 后续依次落地三份子文档：`02_technical_design.md`（技术设计）、`03_constraints.md`（约束设计）、`04_evaluation.md`（评分设计）。
>
> **目标读者**：AI Coding 工具与人工审核者。请按 Phase 顺序执行，**每个 Phase 结束必须产出指定产物并通过门禁，才能进入下一 Phase**。
>
> **版本**：v1.1（新增图片证据处理链路：ImageExtractor → v_image_evidence → search_image_evidence）

---

## 0. 项目目标与范围

**目标**：构建一条从"渗透测试报告 PDF"到"对话式漏洞统计、图表与细节问答"的完整链路。

**核心链路**：
```
deliverables/ (PDF 语料)
  → 语料勘察 (Corpus Profiling)
  → 解析层 (Parse：表格 + 正文 + 图片证据)
  → 入库层 (Load → SQLite)
  → ChatBI 层 (Agent + 五工具 → 统计/图表/细节问答)
```

**MVP 范围**：
- ✅ 漏洞数量、类型分布、风险等级分布、按报告/按类型的对比与排序
- ✅ 柱状图 / 饼图
- ✅ 多轮追问
- ✅ **基于图片 OCR 文本的漏洞细节问答**（如"这个 SQL 注入的 payload 是什么""截图里返回了什么报错"）
- ❌ PDF 解析的 LLM 化（解析层用确定性工具 + OCR，不做端到端 VLM 描述）
- ❌ VLM 生成的图片语义描述（作为 Phase 2 的可选扩展位，MVP 不做）
- ❌ 自主归因推演、开放式建模、多数据源、写操作

**关键原则**（贯穿所有 Phase）：
1. **解析层与 ChatBI 层完全解耦**：ChatBI 只感知 SQLite，不感知 PDF 与图片文件。
2. **解析层不依赖通用 LLM**：表格/正文用 MinerU / pdfplumber；图片用 OCR（确定性），**不启用 VLM 语义描述**。
3. **一切变更走增量**：内容哈希 + 管道版本号驱动，不做无脑全量重跑。
4. **门禁优先于速度**：任何阶段数据质量不达标，宁可不入库，也不污染下游。
5. **图片证据可追溯**：ChatBI 回答图片相关细节时，必须同时给出 OCR 原文与图片文件路径，供人工核对。

---

## 1. 目录结构约定

Coding 工具在开工前，**必须先读取并确认以下目录结构**。若不存在，按此结构创建骨架。

```
chatbi-vuln/
├── deliverables/                  # ★ 交付物语料库（PDF 渗透测试报告的唯一入口）
│   ├── 第一轮渗透测试/            # 轮次
│   │   └── <团队名>/
│   │       ├── 渗透测试报告/*.pdf
│   │       └── 回归测试报告/*.pdf
│   └── 第二轮渗透测试/
│       └── <团队名>/
│           ├── 渗透测试报告/*.pdf
│           └── 回归测试报告/*.pdf
│
├── pipeline/                      # 前置管道（PDF → SQLite），不进入 ChatBI 运行时
│   ├── common/
│   │   └── types.py               # 全局数据结构（CanonicalVulnRecord / ImageRecord / ...）
│   ├── phase0_inventory/
│   │   └── scan_deliverables.py
│   ├── phase1_profile/
│   │   ├── sample_pdfs.py
│   │   ├── inspect_samples.py     # 观察项新增：图片密度、图片类型分布
│   │   └── corpus_profile.json
│   ├── phase2_parse/
│   │   ├── adapters/
│   │   │   ├── base.py
│   │   │   ├── mineru_adapter.py
│   │   │   └── pdfplumber_adapter.py
│   │   ├── locator.py
│   │   ├── extractor.py
│   │   ├── image_extractor.py     # ★ 新增：图片提取 + OCR + 漏洞关联
│   │   ├── quality_gate.py
│   │   └── run_parse.py
│   ├── phase3_load/
│   │   ├── normalizer.py
│   │   ├── dedup.py
│   │   ├── image_loader.py        # ★ 新增：图片证据入库
│   │   ├── retest_loader.py       # ★ 新增：回归复测结果入库
│   │   ├── sqlite_loader.py
│   │   └── run_load.py
│   ├── phase4_incremental/
│   │   ├── index_store.py
│   │   ├── planner.py
│   │   └── run_pipeline.py
│   └── config/
│       ├── header_aliases.yaml
│       ├── severity_map.yaml
│       ├── image_rules.yaml       # ★ 新增：图片类型判定 / OCR 参数 / 关联策略
│       └── pipeline_version.txt
│
├── app/                           # ChatBI 运行时
│   ├── main.py
│   ├── agent/
│   │   ├── definition.py
│   │   └── prompts.py
│   ├── tools/
│   │   ├── get_schema.py
│   │   ├── search_knowledge.py
│   │   ├── execute_sql.py
│   │   ├── search_image_evidence.py   # ★ 新增
│   │   └── render_chart.py
│   ├── db/
│   │   ├── vuln.db
│   │   └── schema.sql
│   └── session.py
│
├── data/
│   ├── file_inventory.json
│   ├── parsed_output/
│   │   └── {pdf_stem}/{batch_id}/
│   │       ├── raw_parsed.json
│   │       ├── located_tables.json
│   │       ├── canonical_records.json
│   │       ├── image_records.json     # ★ 新增
│   │       └── quality_gate.json
│   ├── images/                        # ★ 新增：图片文件落盘（不存 BLOB）
│   │   └── {pdf_stem}/{page}_{idx}.png
│   └── staging/
│
├── tests/
│   ├── pipeline_eval.csv
│   ├── image_eval.csv                 # ★ 新增：图片证据检索评测集
│   └── chat_eval.csv
│
├── docs/
│   ├── 01_master_workflow.md
│   ├── 02_technical_design.md
│   ├── 03_constraints.md
│   └── 04_evaluation.md
│
├── requirements.txt
└── README.md
```

**给 Coding 工具的第一条指令**：
> 先递归列出 `deliverables/` 的内容（文件名、大小、扩展名、子目录），按「轮次 / 团队 / 报告类型」统计数量，不要打开任何 PDF，只做清单。产出 `data/file_inventory.json`（`files[].relative_path` 必须保留完整层级）。若该目录不存在或为空，**停止并报告**，不得凭空生成测试 PDF。

> **`deliverables/` 目录约定（2026-11-08 盘点）**：语料按「轮次 / 团队 / 报告类型」三级组织。
> - 轮次：`第一轮渗透测试`、`第二轮渗透测试`；
> - 团队：当前 6 个（发改委（含粮食物资储备局）和统计局团队、国资委、科委和金融监管局团队、审计局和知识产权局团队、市场监管局（含药监局）团队、经信委和商务委团队、财政局团队）；
> - 报告类型：`渗透测试报告`、`回归测试报告`；
> - 当前共 363 份 PDF（第一轮 191、第二轮 172；2026-11-08 盘点，最终以 `data/file_inventory.json` 为准）；
> - 扫描必须递归，`relative_path` 保留完整层级；不得假设固定深度。

---

## 2. 总体工作流：六个 Phase

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5
目录认知    语料勘察     解析         入库         ChatBI       增量运维
(盘点)      (找规律)   (表/文/图)    (SQLite)    (统计+细节)  (日常运行)
    │           │           │            │            │            │
    ▼           ▼           ▼            ▼            ▼            ▼
inventory   corpus_    canonical_    vuln.db      Agent         ProcessingPlan
 .json      profile    records +     + 索引       + 五工具       + 跳过决策
            .json      image_records
```

**门禁**：每个 Phase 有明确"退出条件"，不满足不得进入下一 Phase。

---

### Phase 0 · 目录认知（Inventory）

| 项 | 内容 |
|---|---|
| **目标** | 建立文件清单基线，不解析内容 |
| **输入** | `deliverables/` |
| **动作** | 递归遍历；记录 `relative_path`、`size`、`mtime_ns`、`ext`；按扩展名分组 |
| **输出** | `data/file_inventory.json` |
| **门禁** | ① PDF 数量 > 0；② 每个文件可读；③ 报告 PDF 总数、总大小、命名规律 |
| **人工检查点** | 确认清单与预期一致；记录版本号命名规律 |

**给 Coding 工具的指令**：
> 只读取元数据，**不得打开 PDF 内容**。输出 JSON 后一句话总结。

---

### Phase 1 · 语料勘察（Corpus Profiling）★ 关键阶段

| 项 | 内容 |
|---|---|
| **目标** | 在写任何解析代码之前，先理解报告长什么样，找出模板规律，决定解析策略 |
| **输入** | `data/file_inventory.json` |
| **动作** | ① 按「轮次 × 团队 × 报告类型」分层随机抽样 5–10 份 PDF（固定 seed，至少覆盖两个轮次与两类报告）；② 用 pdfplumber 提取页数、前 2–3 页文本、所有表格表头；③ **统计每份报告的图片数量、图片所在页、图片平均尺寸**（用 pdfplumber 的 `page.images`）；④ 汇总表头候选、章节标题、风险等级用词、漏洞类型用词，并按轮次/团队标注差异（两轮报告可能模板不同） |
| **输出** | ① `data/sample_notes.md`；② `data/corpus_profile.json` |
| **门禁** | ① 抽样 ≥ 5 份，且覆盖 ≥ 2 个轮次；② `corpus_profile.json` 必须包含表头别名、严重性词表、是否含摘要计数表、表格是否跨页、是否扫描件；③ **必须包含图片统计**：每份报告图片数、图片总占比、典型图片类型推断（截图/图表/流程图）；④ 明确解析策略（主用适配器、是否启用 OCR、KV 兜底） |
| **人工检查点** | 审核者阅读 `sample_notes.md` 与 `corpus_profile.json`，确认策略后**手动签注 `approved: true`** |

**`corpus_profile.json` 新增字段**：
```json
{
  "image_stats": {
    "avg_images_per_report": 12.5,
    "image_page_ratio": 0.35,
    "typical_image_types": ["screenshot", "chart"],
    "images_linked_to_vuln_ratio": 0.8
  },
  "image_strategy": {
    "ocr_enabled": true,
    "ocr_engine": "mineru_builtin",
    "ocr_languages": ["ch", "en"],
    "link_by_page_proximity": true,
    "link_page_window": 1,
    "vlm_description_enabled": false
  }
}
```

**给 Coding 工具的指令**：
> 抽样要真的随机（固定 seed），并按「轮次 / 团队 / 报告类型」分层，避免只抽到单轮或单团队。不要假设所有报告同一模板；发现 ≥ 3 种模板要在 `corpus_profile.json` 分组。图片统计必须做——它决定 ImageExtractor 的策略参数。

---

### Phase 2 · 解析层（Parse：表格 + 正文 + 图片）

| 项 | 内容 |
|---|---|
| **目标** | 把 PDF 转为 `CanonicalVulnRecord[]` + `ImageRecord[]`，输出到 `data/parsed_output/` 与 `data/images/` |
| **输入** | `deliverables/**/*.pdf`（递归；保留含轮次/团队/报告类型的 `relative_path`） + `corpus_profile.json` + `config/header_aliases.yaml` + `config/image_rules.yaml` |
| **动作** | 按"Adapter → Locator → Extractor → **ImageExtractor** → Quality Gate"五段式执行 |
| **输出** | 每份 PDF 一个目录：`raw_parsed.json`、`located_tables.json`、`canonical_records.json`、**`image_records.json`**、`quality_gate.json`；图片文件落盘到 `data/images/` |
| **门禁** | ① `parse_status` ∈ {`pass`, `pending_review`}；② `fail` 不进 Phase 3；③ 有摘要计数表时必须交叉校验（偏差 > 20% 降级 `pending_review`）；④ **图片 OCR 成功率 ≥ 90%**（`ocr_text` 非空的图片数 / 总图片数，若报告图片密度 > 0）；⑤ **图片-漏洞关联率 ≥ 60%**（能关联到某条漏洞记录的图片数 / 总图片数） |
| **人工检查点** | 对 `pending_review` 批次抽样 10%–20% 对照原文；抽查 3–5 张图片的 OCR 文本与原图一致性 |

**关键契约（新增图片结构）**：
```python
@dataclass(frozen=True)
class ImageRecord:
    source_file: str
    source_page: int
    image_index: int                 # 该页内的第几张图片，从 0 开始
    image_path: str                  # 相对 data/images/ 的路径
    image_type: str                  # "screenshot" | "chart" | "unknown"
    ocr_text: str                    # 图片中可读出的文本（payload/响应/报错/URL）
    ocr_confidence: str              # "high" | "medium" | "low"
    linked_vuln_name: str | None     # 通过页码邻近启发式关联
    generated_description: str | None  # MVP 恒为 None（VLM 扩展位）
```

**MVP 明确不做的事**：
- **不启用 VLM 生成图片语义描述**。`generated_description` 字段保留但不填，作为后续扩展位。
- **不把图片 BLOB 写入 SQLite**。图片文件落盘，SQLite 只存路径与 OCR 文本。

**给 Coding 工具的指令**：
> 解析层禁止调用任何通用 LLM。图片处理只做 OCR（MinerU 自带 OCR 引擎），不做语义描述。图片与漏洞的关联用"图片所在页 ± `link_page_window` 页内的漏洞记录"启发式绑定；有多条候选时取页差最小、位置最近的。

---

### Phase 3 · 入库层（Load）

| 项 | 内容 |
|---|---|
| **目标** | 把 `canonical_records.json` + `image_records.json` + `retest_records.json` 归一化、去重、按文件同步写入 `app/db/vuln.db` |
| **输入** | Phase 2 输出 + `config/severity_map.yaml` |
| **动作** | ① 漏洞记录：严重性归一化、类型归一化、去重、按文件同步（DELETE 差集 + UPSERT）；② **图片证据：按文件同步写入 `v_image_evidence`，并维护 FTS5 索引**；③ **回归复测：写入 `v_retest_result`，不写入 `v_vulnerability`** |
| **输出** | `vuln.db` 中 `v_report` / `v_vulnerability` / `v_type_catalog` / `kb_entry` / **`v_image_evidence`** / **`v_retest_result`** / `v_image_evidence_fts` 表 + `pdf_index` 索引表 |
| **门禁** | ① 每文件漏洞入库条数与 `canonical_records.json` 一致；② 归一化后 `severity` 只取四值；③ 无重复 `(source_file, vuln_name, component)`；④ **每文件图片入库条数与 `image_records.json` 一致**；⑤ **FTS5 索引行数 = `v_image_evidence` 行数**；⑥ 事务失败回滚并标 `load_status=fail`；⑦ **回归记录只写 `v_retest_result`，不得写入 `v_vulnerability`** |
| **人工检查点** | 抽查 3 份报告在库中的漏洞记录与图片证据，与原文对照 |

**新增建表脚本片段（`schema.sql` 必须包含）**：
```sql
CREATE TABLE IF NOT EXISTS v_image_evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       INTEGER NOT NULL REFERENCES v_report(id) ON DELETE CASCADE,
    source_file     TEXT    NOT NULL,
    source_page     INTEGER NOT NULL,
    image_index     INTEGER NOT NULL,
    image_path      TEXT    NOT NULL,        -- 相对 data/images/ 的路径
    image_type      TEXT    NOT NULL DEFAULT 'unknown',
    ocr_text        TEXT    NOT NULL DEFAULT '',
    ocr_confidence  TEXT    NOT NULL DEFAULT 'medium',
    linked_vuln_name TEXT,
    generated_description TEXT,              -- MVP 恒为 NULL
    status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','superseded','orphaned')),
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE(source_file, source_page, image_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS v_image_evidence_fts USING fts5(
    ocr_text,
    linked_vuln_name,
    content='v_image_evidence',
    content_rowid='id',
    tokenize='trigram'
);
```

> **分词器说明**：`trigram` 分词器（SQLite 3.34+）对中英文混合文本的检索效果优于默认 `unicode61`，且支持 `LIKE` 风格的子串匹配。若目标 SQLite 版本低于 3.34，回退到 `unicode61`。
>
> **方案 B 新增**：`v_report.report_type` / `parent_report_id` 与 `v_retest_result` 的建表脚本见 `02_technical_design.md` §2。

---

### Phase 4 · ChatBI 层（Serve）

| 项 | 内容 |
|---|---|
| **目标** | 用 OpenAI Agents SDK 构建单 Agent + 五工具的对话式查询（统计 + 图表 + 图片细节） |
| **输入** | `app/db/vuln.db`（只读） |
| **动作** | 实现 Agent、五个 Function tools、SQLiteSession、只读拦截、图表渲染、图片证据检索 |
| **输出** | 可运行的 `app/main.py`；支持"高危漏洞有多少""按类型分布出柱状图""这个 SQL 注入的 payload 是什么" |
| **门禁** | ① 20 条 `chat_eval.csv` 正确率 ≥ 90%；② **10 条 `image_eval.csv` 正确率 ≥ 80%**；③ 非 SELECT 语句 100% 拒绝；④ 每次回答附带 SQL；⑤ 多轮追问能继承筛选条件；⑥ **图片相关回答必须同时返回 `ocr_text` 和 `image_path`** |
| **人工检查点** | 试问 5 个"语料外"问题，确认 Agent 会追问或明确拒绝，不编造；试问 3 个图片细节问题，人工核对 OCR 原文 |

**Agent 工具清单（从四个扩展为五个）**：

| 工具 | 职责 |
|---|---|
| `get_schema()` | 返回五张表的字段、类型、注释、枚举值 |
| `search_knowledge(question)` | 查 `kb_entry`，命中返回预置 SQL |
| `execute_sql(sql)` | 只读校验 → 执行 → 返回结果与 SQL |
| **`search_image_evidence(vuln_name, keywords)`** | **在 `v_image_evidence_fts` 中检索 OCR 文本，返回相关图片的 OCR 原文、图片类型、`image_path`、关联漏洞名** |
| `render_chart(data, chart_type)` | 返回图表配置或本地生成 PNG |

**图片细节问答的典型路径**：
```
用户："那个 SQL 注入的 POC 截图里返回了什么？"
  → Agent 调 search_image_evidence(vuln_name="SQL 注入", keywords=["payload","response","error"])
  → 返回：{ocr_text: "GET /api?id=1' OR 1=1-- HTTP/1.1 ... 200 OK ... MySQL syntax error...", image_path: "..."}
  → Agent 组织回答：结论 + OCR 原文引用 + 图片路径 + 声明"OCR 可能存在识别误差，建议核对原图"
```

---

### Phase 5 · 增量与运维（Incremental & Ops）

| 项 | 内容 |
|---|---|
| **目标** | 日常运行只处理变更文件 |
| **输入** | `deliverables/` 当前状态 + `pdf_index` 表 |
| **动作** | ① 扫描对比 `(size, mtime_ns, content_hash, pipeline_version)`；② 生成 `ProcessingPlan`；③ 只对变更文件执行 Phase 2→3；④ 文件消失则软删除（漏洞 + 图片证据同步软删） |
| **输出** | `ProcessingPlan` + 更新后的 `pdf_index` + 一致性校验日志 |
| **门禁** | ① 未变更文件不得被解析；② 变更文件重跑后无重复、无残留；③ **图片证据与漏洞记录的 `status` 同步**（都 active 或都 orphaned）；④ `pipeline_version` 变更正确触发重跑 |
| **人工检查点** | 新增/替换/删除各模拟一次，验证漏洞与图片证据的一致性 |

**判定顺序**：
```
1. 索引中不存在            → 新文件，重跑
2. pipeline_version 不一致 → 逻辑重跑（含 OCR 参数变更）
3. content_hash 不一致     → 内容重跑
4. 索引存在但文件消失       → 标记待删除（软）
5. 以上都不满足            → 跳过
```

**孤儿软删除需同时覆盖两张表**：
```sql
UPDATE v_report SET status='orphaned' WHERE report_name=?;
UPDATE v_vulnerability SET status='orphaned' WHERE source_file=?;
UPDATE v_image_evidence SET status='orphaned' WHERE source_file=?;
-- FTS5 同步：通过触发器或手动 INSERT INTO v_image_evidence_fts(v_image_evidence_fts) VALUES('rebuild');
```

---

## 3. 阶段间契约（Interface Contracts）

| 从 → 到 | 契约产物 | 格式 |
|---|---|---|
| Phase 0 → 1 | `data/file_inventory.json` | JSON |
| Phase 1 → 2 | `data/corpus_profile.json` | JSON（需 `approved: true`，含 `image_strategy`） |
| Phase 2 → 3 | `canonical_records.json` + **`image_records.json`** + `data/images/*` | JSON 数组 |
| Phase 3 → 4 | `app/db/vuln.db` | SQLite，含 `v_image_evidence` 与 FTS5 表 |
| Phase 4 内部 | Agent + 五工具 | 只读访问 `vuln.db` |
| Phase 5 → 2/3 | `ProcessingPlan` | JSON |

**铁律**：任何阶段不得直接修改上游产物。要改，改配置或代码后重跑该阶段。

---

## 4. 给 Coding 工具的执行提示

1. **顺序执行，不跳 Phase**。每 Phase 结束汇报"产物路径 + 门禁结论"。
2. **禁止假设**。Phase 1 未抽样前不得假设版式；`corpus_profile.json` 未 `approved` 前不得进 Phase 2。
3. **中间产物全部落盘**，含图片文件。
4. **配置外置**。表头别名、严重性映射、**图片规则**、表名白名单全部放 `config/`。
5. **失败不静默**。解析失败、门禁不通过、事务回滚写入 `data/staging/` 并告警。
6. **不生成假数据**。`deliverables/` 为空则停止报告。
7. **单文件可独立测试**。每个 Phase 入口支持 `--file` 参数。
8. **写测试**。三份评测集先建骨架。
9. **图片路径使用相对路径**（相对 `data/images/`），避免绝对路径污染数据库。
10. **OCR 文本不做清洗后再存**。原始 OCR 文本与清洗后文本分开存储（`ocr_text` 存原文），检索时用清洗后文本，便于审计。

---

## 5. 后续三份子文档的定位

### 5.1 技术设计文档（`02_technical_design.md`）
每个模块的类图、函数签名、数据结构、`schema.sql` 全文、Locator 算法、Extractor 流程、**ImageExtractor 的 OCR 与关联逻辑**、Quality Gate 实现、Agent instructions、五工具 Function Schema、UPSERT 与差集删除 SQL。

### 5.2 约束设计文档（`03_constraints.md`）
命名规范、依赖边界、只读规则、错误处理与日志规范、配置版本管理、**图片处理的安全约束（OCR 注入防护、敏感信息不外传）**。

### 5.3 评分设计文档（`04_evaluation.md`）
解析层召回率、**图片 OCR 成功率与关联率**、入库层重复率、ChatBI 查询正确率、**图片证据检索命中率**、端到端耗时；每 Phase 的及格/良好/优秀线。

---

## 6. 风险与开放问题

| # | 风险/问题 | 影响 Phase | 建议 |
|---|---|---|---|
| 1 | 报告含扫描件，需 OCR | 1/2 | Phase 1 统计扫描件比例；> 30% 时解析策略引入 OCR |
| 2 | 同一漏洞多报告重复 | 3 | MVP 按文件内唯一；跨报告去重留作扩展 |
| 3 | MinerU 静默丢块 | 2 | 强制摘要计数交叉校验 |
| 4 | PDF 格式演进使 Locator 失效 | 5 | 别名配置化，新模板更新 profile 重跑 Phase 1 |
| 5 | 报告敏感信息能否用云端 LLM | 4 | ChatBI 的 LLM 只接触 SQLite 结构化摘要与 OCR 文本，不接触原图；解析层本地 |
| 6 | `deliverables/` 三级子目录（轮次/团队/报告类型） | 0 | 递归扫描；`relative_path` 保留完整层级；不得假设固定深度 |
| 7 | **OCR 文本可能含提示注入**（截图中的恶意文字） | 4 | `search_image_evidence` 返回的文本在 prompt 中显式标注为"不可信 OCR 内容"，不作为指令执行 |
| 8 | **OCR 识别误差导致 payload 失真** | 2/4 | 保存原始 OCR 文本 + 原图路径；回答时声明"建议核对原图"；评测集人工标注 OCR 准确率 |
| 9 | **图片与漏洞关联的启发式可能错配** | 2 | 关联率门禁 ≥ 60%；错配的图片仍入库但 `linked_vuln_name` 标 `UNLINKED`，供全库检索 |
| 10 | **图片密度高导致解析耗时与存储膨胀** | 2/3 | 图片文件落盘；解析可选并发；对超大图（> 2MB）先缩放再 OCR |

---

## 7. 验收清单（Definition of Done）

- [ ] `deliverables/` 中 ≥ 90% 的 PDF 经过 Phase 2 且 `parse_status=pass`
- [ ] `pdf_index` 中每个文件有完整 `parse_status` 与 `load_status`
- [ ] `v_vulnerability` 无重复 `(source_file, vuln_name, component)`
- [ ] **`v_image_evidence` 无重复 `(source_file, source_page, image_index)`**
- [ ] **`v_image_evidence_fts` 行数 = `v_image_evidence` 中 `status='active'` 的行数**
- [ ] ChatBI 能正确回答：总漏洞数、类型分布（柱状图）、风险等级分布、按报告对比
- [ ] **ChatBI 能正确回答至少 3 类图片细节问题**：payload、响应/报错、请求路径
- [ ] `chat_eval.csv` 正确率 ≥ 90%；**`image_eval.csv` 正确率 ≥ 80%**
- [ ] 新增 1 份 PDF 后，`run_pipeline.py` 只处理该文件，其余标 `skipped`
- [ ] 删除 1 份 PDF 后，漏洞与图片证据记录同步标 `orphaned`
- [ ] 非 SELECT 语句 100% 被 `execute_sql` 拒绝
- [ ] 图片相关回答 100% 附带 `ocr_text` 与 `image_path`
- [ ] 四份文档（01–04）均已落地并交叉引用一致

---

**下一步**：确认本总纲后，产出 `03_constraints.md` → `04_evaluation.md`（`02_technical_design.md` 已同步更新）。