# ChatBI-Vuln 项目 · 已知陷阱清单（Pitfalls）

> **文档定位**：收集"文档没明说、但一试就错"的地方。每条包含症状、原因、规避方式。
>
> **使用方式**：
> 1. 开工某个模块前，扫一眼对应段落；
> 2. 遇到报错时，先在本文件搜索关键词（如 `ON CONFLICT`、`FTS5`、`trigram`）；
> 3. 发现新坑时，追加到文末，不修改历史条目。

---

## 1. SQLite 相关

### P-SQL-001 · `ON CONFLICT` 不支持表达式索引

- **症状**：执行 `INSERT ... ON CONFLICT(source_file, vuln_name, COALESCE(component,'')) DO UPDATE ...` 时，报 `near "COALESCE": syntax error`。
- **原因**：SQLite 的冲突子句只接受列名，不支持表达式。
- **规避**：MVP 采用 D-007 的方案 B——入库前把 `component=None` 统一转为 `""`，冲突子句写作 `ON CONFLICT(source_file, vuln_name, component)`。
- **影响**：`pipeline/phase3_load/sqlite_loader.py`、`image_loader.py`

### P-SQL-002 · `PRAGMA journal_mode=WAL` 在只读连接上可能报错

- **症状**：`app/` 以 `mode=ro` 打开 `vuln.db` 时，执行 `PRAGMA journal_mode=WAL` 报 `attempt to write a readonly database`。
- **原因**：WAL 模式设置在数据库文件层面，只读连接无法修改。
- **规避**：`schema.sql` 里的 `PRAGMA journal_mode=WAL` 只在建库时执行一次（`pipeline` 侧）；`app/` 侧不执行此 PRAGMA，直接 `sqlite3.connect("file:vuln.db?mode=ro", uri=True)`。
- **影响**：`app/tools/execute_sql.py`、`app/session.py`

### P-SQL-003 · 空字符串 vs NULL 的唯一性行为不同

- **症状**：`component=''` 的记录与 `component=NULL` 的记录在唯一索引下不冲突（NULL 不参与唯一性），导致"看似重复"的记录被允许。
- **原因**：SQLite 遵循 SQL 标准——`NULL != NULL`。
- **规避**：D-007 已明确 MVP 统一转空字符串。若未来需要区分，改用生成列方案 A。
- **影响**：`pipeline/phase3_load/sqlite_loader.py`

### P-SQL-004 · `executemany` 与 `UPSERT` 的事务边界

- **症状**：批量 `executemany` 中途失败时，部分记录已写入，导致数据不一致。
- **原因**：`executemany` 内部逐条执行，不自动包事务。
- **规避**：`sqlite_loader.py` 中显式 `BEGIN` ... `COMMIT` 包裹整个文件的差集删除 + UPSERT；异常时 `ROLLBACK`。
- **影响**：`pipeline/phase3_load/sqlite_loader.py`、`image_loader.py`

### P-SQL-005 · `sqlite3.Row` 与 `dict` 混用导致字段访问错误

- **症状**：`row['severity']` 在某些查询结果中报 `TypeError`。
- **原因**：连接未设置 `row_factory = sqlite3.Row` 时，返回的是 tuple。
- **规避**：所有连接初始化后立即 `conn.row_factory = sqlite3.Row`。
- **影响**：所有读写 SQLite 的模块

---

## 2. FTS5 相关

### P-FTS-001 · 外部内容表的触发器在批量插入时可能漏触发

- **症状**：`v_image_evidence` 有 1000 行，`v_image_evidence_fts` 只有 800 行。
- **原因**：某些 SQLite 版本在 `INSERT ... SELECT` 或批量 `executemany` 时，触发器可能不按预期触发（已知历史 bug）。
- **规避**：批量入库结束后执行 `INSERT INTO v_image_evidence_fts(v_image_evidence_fts) VALUES('rebuild');`，强制重建索引；或改为在批量入库后统一执行。
- **验证**：`tests/eval/check_fts_consistency.py` 定期校验。
- **影响**：`pipeline/phase3_load/image_loader.py`

### P-FTS-002 · trigram 分词器要求 SQLite ≥ 3.34

- **症状**：建库时报 `no such tokenizer: trigram`。
- **原因**：`trigram` 在 SQLite 3.34.0（2020-12-01）引入。
- **规避**：`10_environment.md` 中写明版本要求；启动时用 `sqlite3.sqlite_version` 检查，低于 3.34 时降级到 `unicode61` 并告警。
- **影响**：`app/db/schema.sql`、`pipeline/common/types.py` 的版本检查

### P-FTS-003 · FTS5 的 `MATCH` 语法对特殊字符敏感

- **症状**：`search_image_evidence(keywords=['OR 1=1'])` 报 `fts5: syntax error near "="`。
- **原因**：FTS5 的 `MATCH` 把 `=`、`"`、`*`、`(`、`)`、`:`、`^`、`NEAR` 等视为语法字符。
- **规避**：`search_image_evidence` 内部对每个关键词做转义——用双引号包裹整个词（`"OR 1=1"`），并转义内部的 `"` 为 `""`；多个词用空格连接。
- **实现**：
  ```python
  def escape_fts_keyword(kw: str) -> str:
      return '"' + kw.replace('"', '""') + '"'
  ```
- **影响**：`app/tools/search_image_evidence.py`

### P-FTS-004 · `ORDER BY rank` 只在 `MATCH` 查询中可用

- **症状**：`SELECT ... FROM v_image_evidence_fts ORDER BY rank` 报错。
- **原因**：`rank` 是 FTS5 的特殊列，只在含 `MATCH` 的查询中有效。
- **规避**：确保 `search_image_evidence` 的 SQL 一定包含 `WHERE v_image_evidence_fts MATCH ?`；若不需相关性排序，改用 `ORDER BY e.source_page`。
- **影响**：`app/tools/search_image_evidence.py`

### P-FTS-005 · `rebuild` 命令只在外部内容表模式下可用

- **症状**：`INSERT INTO v_image_evidence_fts(v_image_evidence_fts) VALUES('rebuild')` 报错。
- **原因**：`rebuild` 要求 FTS 表声明了 `content='v_image_evidence'`。
- **规避**：schema 中已声明 `content='v_image_evidence', content_rowid='id'`（见 02 §2）。若未来改为独立 FTS 表，则需用 `INSERT` 维护，不能用 `rebuild`。
- **影响**：`pipeline/phase3_load/image_loader.py`

---

## 3. PDF 解析相关

### P-PDF-001 · pdfplumber 的 `page.images` 需要配合 `crop` 才能提取图片

- **症状**：直接 `page.to_image()` 保存的图片是全白或全黑。
- **原因**：`page.to_image()` 渲染整页，而 `page.images` 只给出图片的 bbox，需要 `page.crop(bbox).to_image(resolution=200)` 才能提取到实际图片区域。
- **规避**：`pdfplumber_adapter.py` 中对每个 `page.images` 的 bbox 调用 `page.crop(bbox).to_image(resolution=200).save(...)`。
- **影响**：`pipeline/phase2_parse/adapters/pdfplumber_adapter.py`

### P-PDF-002 · MinerU 不同版本的 `content_list.json` 结构不同

- **症状**：升级 MinerU 后，`raw_parsed.json` 解析报 `KeyError: 'table_body'`。
- **原因**：MinerU 3.x 前后的字段名有变化（`table_body` → `table`，或 `type` 值变化）。
- **规避**：`mineru_adapter.py` 中做版本探测——读取 MinerU 输出的 `meta.json` 中的版本号，按版本分支处理；若无法探测，尝试多个字段名，取第一个非空的。
- **影响**：`pipeline/phase2_parse/adapters/mineru_adapter.py`

### P-PDF-003 · MinerU 静默丢块

- **症状**：解析不报错，但 `content_list.json` 中缺少某些页的表格块。
- **原因**：MinerU 在某些边界情况下（超长表格、复杂排版）会丢弃整块，接口仍返回成功。
- **规避**：`quality_gate.py` 强制启用"摘要计数交叉校验"（E-PARSE-005），若报告中含 "Critical: 2" 这类声明，则与提取结果对比，偏差 > 20% 时降级为 `pending_review`。
- **影响**：`pipeline/phase2_parse/quality_gate.py`

### P-PDF-004 · pdfplumber 对扫描件返回空文本

- **症状**：`page.extract_text()` 返回空字符串，`page.extract_tables()` 返回 `[]`。
- **原因**：扫描件是图片，没有文本层。
- **规避**：Phase 1 的 `inspect_sample` 中统计 `is_scanned`（前 3 页平均字符数 < 50）；若报告为扫描件，MVP 阶段可跳过并记录到 `pending_review`，不进入 Phase 3。
- **影响**：`pipeline/phase1_profile/inspect_samples.py`、`quality_gate.py`

### P-PDF-005 · 跨页表格需要合并

- **症状**：一个 20 行的漏洞表格被拆成 3 个表格，每个都只有表头 + 部分行。
- **原因**：PDF 分页导致表格被切断。
- **规避**：`Adapter` 中做跨页合并——若相邻两个 `ParsedTable` 的表头完全一致且页码连续，拼接 `rows`，`page_start` 取第一个、`page_end` 取最后一个。
- **影响**：`pipeline/phase2_parse/adapters/base.py` 的公共方法

---

## 4. OCR 相关

### P-OCR-001 · PaddleOCR 首次调用下载模型到 `~/.paddleocr/`

- **症状**：首次运行卡住数分钟无输出。
- **原因**：PaddleOCR 自动下载检测/识别/方向分类三个模型。
- **规避**：`10_environment.md` 中写明"首次运行前执行 `paddleocr --version` 预下载"；生产环境可离线预置模型到指定目录。
- **影响**：`pipeline/phase2_parse/image_extractor.py`

### P-OCR-002 · OCR 输出 URL 中间插空格

- **症状**：OCR 识别出 `/api / users`（中间有空格），FTS 检索 `/api/users` 查不到。
- **原因**：OCR 引擎对字符间距的判断误差。
- **规避**：
  - 入库时**不清洗**（D-011）；
  - `search_image_evidence` 检索时，对关键词做"空格容忍"扩展——生成原词与去空格变体两个版本，用 OR 连接。
- **影响**：`app/tools/search_image_evidence.py`

### P-OCR-003 · 大图直接 OCR 导致内存溢出

- **症状**：处理超过 5000px 的图片时进程被 OOM kill。
- **原因**：PaddleOCR 会把整个图片加载为 numpy 数组，长宽各 5000px 时占用数 GB。
- **规避**：`image_rules.yaml` 的 `resize.max_side_px: 2048`；`image_extractor.py` 中用 Pillow 先缩放再 OCR。
- **影响**：`pipeline/phase2_parse/image_extractor.py`

### P-OCR-004 · OCR 结果含大量换行和制表符

- **症状**：`ocr_text` 中每个 token 之间有 `\n`，导致 FTS 分词异常。
- **原因**：OCR 引擎按行输出。
- **规避**：入库时不处理（D-011）；FTS 的 `trigram` 分词器对换行不敏感，检索时不受影响；但 `search_image_evidence` 返回给 Agent 时，用 `re.sub(r'\s+', ' ', text)` 压缩为单行再返回。
- **影响**：`app/tools/search_image_evidence.py`

---

## 5. OpenAI Agents SDK 相关

### P-AGT-001 · Agent 重试可能重复调用有副作用的工具

- **症状**：`execute_sql` 被调用两次，或 `feedback_writer` 写入重复记录。
- **原因**：Agents SDK 在 LLM 输出解析失败或工具调用失败时会自动重试。
- **规避**：
  - `execute_sql` 是只读的，重试无害；
  - 若未来加入 `feedback_writer`，写入需幂等（用 `INSERT OR IGNORE` + 唯一键）。
- **影响**：`app/tools/execute_sql.py`、未来的 `feedback_writer.py`

### P-AGT-002 · `SQLiteSession` 在多进程下不共享

- **症状**：CLI 开两个窗口，问同样的问题，第二个窗口不知道第一个窗口的历史。
- **原因**：`SQLiteSession` 的数据库连接在每个进程独立。
- **规避**：MVP 单进程；多进程场景明确不支持，写入 `05_decisions.md` 的开放问题。
- **影响**：`app/session.py`

### P-AGT-003 · 多轮对话中 Agent 不知道上一轮的 SQL 结果

- **症状**：用户问"高危有多少"→"中危呢"→"再按类型拆一下"，第三轮 Agent 生成的 SQL 没有继承前两轮的筛选条件。
- **原因**：`execute_sql` 返回的结果（表格数据）不会自动出现在下一轮的对话上下文中——只有"我执行了 SQL，结果是 N"这一句话在历史里。
- **规避**：`execute_sql` 返回 JSON 时附带 `previous_filters` metadata（如 `{"severity": "高危"}`），Agent instructions 明确要求"若用户问题省略主语，先读上一轮 `previous_filters`"。
- **影响**：`app/tools/execute_sql.py`、`app/agent/definition.py` 的 instructions

### P-AGT-004 · 工具调用的 JSON Schema 对 LLM 生成有强约束

- **症状**：LLM 生成的 `keywords` 参数是字符串而非数组，导致 `search_image_evidence` 报错。
- **原因**：Function tool 的签名如果写成 `keywords: list[str]`，多数模型的 function calling 能正确处理；但少数模型可能退化为字符串。
- **规避**：工具内部做类型宽容——若 `keywords` 是 `str`，自动包成 `[keywords]`；同时 Agent instructions 中明确"`keywords` 必须是字符串数组"。
- **影响**：`app/tools/search_image_evidence.py`

---

## 6. 依赖与版本相关

### P-DEP-001 · `trigram` 分词器依赖 SQLite 编译选项

- **症状**：某些系统自带的 SQLite 未启用 FTS5 或 `trigram`。
- **规避**：`10_environment.md` 中提供 `sqlite_compileoption_used('ENABLE_FTS5')` 的检查命令；CI 中强制检查版本。
- **影响**：CI 配置、启动检查

### P-DEP-002 · PaddleOCR 的依赖与 numpy 版本强耦合

- **症状**：`pip install -r requirements.txt` 后，`import paddleocr` 报 `numpy` 版本不兼容。
- **原因**：PaddleOCR 对 numpy 有精确的版本要求。
- **规避**：`requirements.txt` 中锁定 `numpy==<特定版本>`，见 `10_environment.md`。
- **影响**：`requirements.txt`

### P-DEP-003 · OpenAI Agents SDK 的版本与 `openai` 包强耦合

- **症状**：升级 `openai` 后，`from agents import Agent` 报错。
- **原因**：`agents` 对 `openai` 的版本有精确依赖。
- **规避**：`requirements.txt` 中同时锁定 `openai==<v>` 与 `openai-agents==<v>`，见 `10_environment.md`。
- **影响**：`requirements.txt`

### P-DEP-004 · 不同平台的路径分隔符

- **症状**：Linux 上开发的代码在 Windows 上跑，`image_path` 中出现 `\`，前端加载 404。
- **原因**：`os.path.join` 在 Windows 上返回 `\` 分隔符。
- **规避**：`image_path` 统一使用 `PurePosixPath` 生成，或用 `Path.as_posix()` 转换。
- **影响**：`pipeline/phase2_parse/image_extractor.py`、`app/tools/search_image_evidence.py`

---

## 7. 日志与错误处理相关

### P-LOG-001 · 日志中的 JSON 序列化失败

- **症状**：`logger.info(f"... {obj}")` 时，`obj` 含 `datetime` 或 `Path` 等不可序列化对象，导致日志报错。
- **规避**：日志 handler 中配置 `json.dumps(..., default=str)`。
- **影响**：`pipeline/common/logging.py`

### P-LOG-002 · 异常栈被吞

- **症状**：入库失败但只看到"load failed"，没有异常栈，无法定位。
- **原因**：`except Exception as e: logger.error(str(e))` 丢掉了栈。
- **规避**：`logger.exception(...)` 或 `logger.error(..., exc_info=True)`。
- **影响**：所有 `except` 块

### P-LOG-003 · 循环内的日志刷屏

- **症状**：处理 1000 张图片时，每张都打一条 INFO，日志文件瞬间 GB 级。
- **规避**：循环内的日志改用 `DEBUG` 级别；每处理 100 条打一条 `INFO` 汇总；告警只用 `WARN` 以上。
- **影响**：`image_extractor.py`、`sqlite_loader.py`

---

## 8. 评测与测试相关

### P-EVAL-001 · mock 的 `pdfplumber` 返回值与真实行为不符

- **症状**：单测中 mock 了 `page.extract_tables()` 返回二维列表，但真实 pdfplumber 返回的是 `None` 与列表的混合。
- **规避**：`07_fixtures.md` 提供的合成 PDF 用于集成测试；单测中 mock 的返回值必须从真实报告中提取样本（`tests/fixtures/pdfplumber_response_samples.json`）。
- **影响**：`tests/test_*.py`

### P-EVAL-002 · 评测集与 fixture 混用

- **症状**：评测集里的 `expected_*` 用 fixture 的数据填，导致"评测通过了但真实报告不行"。
- **规避**：`07_fixtures.md` 明确定义 fixture 与评测集的区分——fixture 用于单测，评测集用于质量评测，两者不混用。
- **影响**：`tests/` 目录组织

### P-EVAL-003 · 评测时 LLM 温度导致答案波动

- **症状**：同一问题跑两次，E-CHAT-001 正确率从 0.92 变到 0.88。
- **原因**：LLM 的温度参数导致非确定性。
- **规避**：评测时固定 `temperature=0`；若模型不支持，在评测报告中记录波动范围，门禁线预留 5% 缓冲（如要求 ≥ 0.90 时，实际按 0.85 判定）。
- **影响**：`tests/eval/eval_chat.py`

---

## 附录 · 陷阱关键词索引

| 关键词 | 对应条目 |
|---|---|
| `ON CONFLICT` / `COALESCE` | P-SQL-001 |
| `WAL` / `readonly` | P-SQL-002 |
| `trigram` / `tokenizer` | P-FTS-002、P-DEP-001 |
| `MATCH` / `syntax error` | P-FTS-003 |
| `rebuild` / FTS 一致性 | P-FTS-001、P-FTS-005 |
| `page.images` / 全黑 | P-PDF-001 |
| `content_list.json` / `KeyError` | P-PDF-002 |
| 静默丢块 / 计数不符 | P-PDF-003 |
| 扫描件 / 空文本 | P-PDF-004 |
| 跨页表格 | P-PDF-005 |
| `paddleocr` / 下载 | P-OCR-001 |
| URL 空格 | P-OCR-002 |
| OOM / resize | P-OCR-003 |
| `SQLiteSession` / 多进程 | P-AGT-002 |
| `previous_filters` / 多轮 | P-AGT-003 |
| `keywords` 类型错误 | P-AGT-004 |
| `as_posix` / 路径分隔符 | P-DEP-004 |
| `exc_info` / 异常栈 | P-LOG-002 |

**发现新坑时**：按 `P-<模块>-<序号>` 追加，并更新此索引表。