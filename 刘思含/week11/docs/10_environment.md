# ChatBI-Vuln 项目 · 环境搭建（Environment）

> **文档定位**：从零到"能跑第一个 Phase"的完整步骤。避免 AI Coding 工具"照文档写代码，跑的时候发现依赖缺失/版本不对"。
>
> **使用方式**：按 §1 → §5 顺序执行。每步都有验证命令，验证失败时查 §6 常见问题。

---

## 1. 系统要求

| 项 | 最低要求 | 推荐 | 检查命令 |
|---|---|---|---|
| 操作系统 | Linux / macOS | Ubuntu 22.04 | `uname -a` |
| Python | 3.11 | 3.12 | `python --version` |
| SQLite | 3.34 | 3.45+ | `sqlite3 --version` |
| 内存 | 8 GB | 16 GB（OCR + LLM） | `free -h` |
| 磁盘 | 5 GB（含模型） | 20 GB | `df -h .` |
| 网络 | 能访问 PyPI 与 OpenAI API | — | — |

**SQLite 版本必须 ≥ 3.34**，因为 `trigram` 分词器（D-008）在 3.34.0 才引入。检查方式：

```bash
python -c "import sqlite3; print(sqlite3.sqlite_version); print(sqlite3.connect(':memory:').execute(\"SELECT sqlite_compileoption_used('ENABLE_FTS5')\").fetchone())"
# 期望：版本 ≥ 3.34，且 (1,)
```

**若系统 SQLite 低于 3.34**：
- Ubuntu：`apt install libsqlite3-dev` 后重装 Python，或使用 `pyenv` 编译带新版 SQLite 的 Python；
- macOS：`brew install sqlite` 并确保 Python 链接到新版；
- 实在无法升级：降级到 `unicode61`（F-04），接受中文检索召回的损失。

---

## 2. 环境创建

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 2. 升级 pip
pip install --upgrade pip

# 3. 安装依赖
pip install -r requirements.txt
```

### 2.1 `requirements.txt` 参考内容

**必须锁定精确版本**（C-DEP-011）。以下版本为验证过的组合，可在项目中直接使用：

```
# Core
python-dotenv==1.0.1
pydantic==2.14.3
pyyaml==6.0.2

# SQLite & 数据处理
# （sqlite3 是 Python 标准库，无需安装）
pandas==2.2.3

# PDF 解析
pdfplumber==0.11.4
reportlab==4.2.5              # 用于生成测试 fixture
# mineru: 按项目需要选择安装方式，见 §3

# OCR（二选一，默认 PaddleOCR）
paddleocr==2.9.1
paddlepaddle==2.6.2
numpy==1.26.4                 # PaddleOCR 对 numpy 版本敏感（P-DEP-002）
opencv-python==4.11.0.86      # 显式锁定：适配 numpy 1.26.4（P-DEP-002）
# tesseract 需要系统安装，见 §3.2

# 图片处理
Pillow==11.0.0

# ChatBI（已验证组合：openai 1.109.1 + openai-agents 0.1.0 + pydantic 2.14.3 兼容）
openai==1.109.1
openai-agents==0.1.0          # 版本需与 openai 匹配（P-DEP-003）

# 测试
pytest==8.3.3
pytest-cov==6.0.0
pytest-asyncio==0.24.0
jsonschema==4.23.0
ruff==0.7.3
mypy==1.13.0
```

**版本说明**：
- `numpy==1.26.4` 是 PaddleOCR 2.9.x 的已知兼容版本；升级到 2.x 会报错；
- `openai` 与 `openai-agents` 的版本强耦合，升级前查 [Agents SDK 的 release notes](https://github.com/openai/agents) 确认兼容性；
- 若使用 Tesseract 替代 PaddleOCR，可去掉 `paddleocr` / `paddlepaddle` / `numpy` / `opencv-python` 四行，但需保留 `Pillow`。

---

## 3. 可选依赖安装

### 3.1 MinerU（推荐用于复杂 PDF）

MinerU 的安装方式取决于是否使用 GPU：

```bash
# CPU 版本（轻量，适合测试）
pip install mineru
python -m mineru --version

# 若使用 GPU（推荐用于大量报告）
# 先安装 PyTorch（按 https://pytorch.org 选择 CUDA 版本）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install mineru

# 验证
mineru -p tests/fixtures/pdfs/simple_table.pdf -o /tmp/mineru_test --format json
ls /tmp/mineru_test/
```

**注意**：
- MinerU 首次运行会下载模型（约 1–2 GB）到 `~/.cache/mineru/`；
- 若离线环境，需提前把模型拷入；
- MinerU 版本变化时 `content_list.json` 结构可能变化（P-PDF-002），Adapter 需做版本兼容。

### 3.2 Tesseract（PaddleOCR 的替代，见 F-02）

```bash
# Ubuntu
sudo apt install tesseract-ocr tesseract-ocr-chi-sim

# macOS
brew install tesseract tesseract-lang

# 验证
tesseract --version
tesseract --list-langs    # 应包含 chi_sim 和 eng

# Python 绑定
pip install pytesseract==0.3.13
```

### 3.3 PaddleOCR 模型预下载

PaddleOCR 首次调用会自动下载模型（P-OCR-001），离线环境需手动预下载：

```bash
# 预下载检测、识别、方向分类模型
python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='ch')"
ls ~/.paddleocr/    # 应包含 det/ rec/ cls/ 三个目录
```

---

## 4. 配置文件初始化

```bash
# 从模板拷贝（如果项目提供了 .env.example）
cp .env.example .env

# 编辑 .env，填入必要配置
# OPENAI_API_KEY=sk-...
# VULN_DB_PATH=./app/db/vuln.db
# CONFIG_DIR=./pipeline/config
# DATA_DIR=./data
```

**`.env` 中不得出现的内容**（C-SEC-001）：
- 任何 PDF 原文或图片内容；
- 内网 IP、域名、凭证。

**`.env` 必须加入 `.gitignore`**。

---

## 5. 首次运行验证

按顺序执行以下命令，每步都要通过：

### 5.1 建库

```bash
sqlite3 app/db/vuln.db < app/db/schema.sql
```

**验证**：

```bash
sqlite3 app/db/vuln.db ".tables"
# 期望输出包含：
# kb_entry  pdf_index  v_image_evidence  v_image_evidence_fts  v_report  v_type_catalog  v_vulnerability

sqlite3 app/db/vuln.db "SELECT COUNT(*) FROM v_type_catalog;"
# 期望：10

sqlite3 app/db/vuln.db "INSERT INTO v_image_evidence(report_id, source_file, source_page, image_index, image_path, image_type, ocr_text, ocr_confidence, created_at, updated_at) VALUES (1, 'test.pdf', 1, 0, 'test/1_0.png', 'screenshot', 'test ocr text', 'high', '2026-01-01', '2026-01-01');"
# 若报错 FOREIGN KEY，说明 v_report 中没有 id=1 的记录——这是预期的，改用：
sqlite3 app/db/vuln.db "PRAGMA foreign_keys=OFF; INSERT INTO v_image_evidence(report_id, source_file, source_page, image_index, image_path, image_type, ocr_text, ocr_confidence, created_at, updated_at) VALUES (1, 'test.pdf', 1, 0, 'test/1_0.png', 'screenshot', 'test ocr text', 'high', '2026-01-01', '2026-01-01');"

# 验证 FTS5 触发器
sqlite3 app/db/vuln.db "SELECT COUNT(*) FROM v_image_evidence_fts;"
# 期望：1

sqlite3 app/db/vuln.db "SELECT * FROM v_image_evidence_fts WHERE v_image_evidence_fts MATCH '\"ocr\"';"
# 期望：能查到刚插入的记录

# 清理测试数据
sqlite3 app/db/vuln.db "DELETE FROM v_image_evidence WHERE source_file='test.pdf';"
```

### 5.2 生成测试 fixture

```bash
python tests/fixtures/build_fixtures.py
```

**验证**：

```bash
ls tests/fixtures/pdfs/
# 期望：simple_table.pdf  no_table.pdf  table_with_image.pdf  spanning_table.pdf  no_vuln.pdf

ls tests/fixtures/images/
# 期望：screenshot_payload.png  screenshot_error.png  injection_attack.png  large_image.png

ls tests/fixtures/db/
# 期望：seed.db  seed.sql
```

### 5.3 跑测试

```bash
pytest tests/ -v --cov=pipeline --cov=app --cov-report=term-missing
```

**期望**：
- 所有测试通过（此时 `pipeline/` 和 `app/` 可能是空骨架，测试可能是 `skip` 状态）；
- 覆盖率显示但可能为 0（正常，代码还没写）；
- 约束测试 `test_dependency_boundary.py` 通过（空骨架不违反依赖边界）。

### 5.4 跑一个最小端到端（可选）

```bash
# 用 fixture 的 PDF 跑 Phase 2
python -m pipeline.phase2_parse.run_parse \
    --file tests/fixtures/pdfs/simple_table.pdf \
    --profile tests/fixtures/corpus_profile_min.json \
    --config-dir pipeline/config \
    --output-dir /tmp/parsed_output \
    --image-output-root /tmp/images

# 检查输出
cat /tmp/parsed_output/simple_table/latest/canonical_records.json
# 期望：3 条记录
```

**注意**：`corpus_profile_min.json` 是给 fixture 用的最小 profile（`approved: true`），与真实 `corpus_profile.json` 分开。若项目未提供，需手动创建：

```json
{
  "schema_version": "1.0",
  "parse_strategy": {
    "primary_adapter": "pdfplumber",
    "fallback_adapter": "pdfplumber",
    "kv_fallback_enabled": true,
    "vlm_description_enabled": false
  },
  "image_strategy": {
    "ocr_enabled": true,
    "ocr_engine": "paddleocr",
    "ocr_languages": ["ch", "en"],
    "link_by_page_proximity": true,
    "link_page_window": 1
  },
  "header_aliases_observed": {},
  "severity_vocabulary": ["High", "Medium", "Low"],
  "approved": true,
  "approved_by": "fixture",
  "approved_at": "2026-01-01"
}
```

---

## 6. 常见安装问题

### 6.1 `no such tokenizer: trigram`

**原因**：SQLite 版本 < 3.34。

**解决**：
1. 检查版本：`python -c "import sqlite3; print(sqlite3.sqlite_version)"`；
2. 若低于 3.34，按 §1 升级；
3. 若无法升级，改 `schema.sql` 的 `tokenize='unicode61'`（F-04）。

### 6.2 `import paddleocr` 报 numpy 版本错误

**原因**：PaddleOCR 对 numpy 版本强依赖（P-DEP-002）。

**解决**：
```bash
pip uninstall numpy -y
pip install numpy==1.26.4
```

### 6.3 MinerU 首次运行卡住

**原因**：正在下载模型（约 1–2 GB）。

**解决**：
- 等待（视网络 5–20 分钟）；
- 或按 §3.1 预下载；
- 离线环境：从其他机器拷贝 `~/.cache/mineru/` 到目标机器。

### 6.4 `openai-agents` 与 `openai` 版本冲突

**原因**：Agents SDK 对 `openai` 的版本有精确依赖（P-DEP-003）。

**解决**：
```bash
pip install openai==1.54.4 openai-agents==0.1.0
# 若报错，查看 SDK 的 requirements：
pip show openai-agents | grep Requires
# 按要求的版本重新安装
```

### 6.5 PaddleOCR 报 `libgomp.so.1` 缺失（Ubuntu）

**原因**：缺少 OpenMP 运行库。

**解决**：
```bash
sudo apt install libgomp1
```

### 6.6 Windows 上路径分隔符问题（P-DEP-004）

**症状**：`image_path` 中出现 `\`，前端 404。

**解决**：
- 代码中统一用 `Path.as_posix()` 或 `PurePosixPath` 生成路径；
- 若已入库的路径有问题，执行：
  ```sql
  UPDATE v_image_evidence SET image_path = REPLACE(image_path, '\\', '/');
  ```

### 6.7 `sqlite3.OperationalError: database is locked`

**原因**：多个进程同时访问 `vuln.db`，且未用 WAL 模式。

**解决**：
- 确认 `schema.sql` 第一行有 `PRAGMA journal_mode=WAL;`；
- `pipeline` 运行时独占写，`app` 只读（D-001），两者不应同时运行；
- 若必须并发，使用 `sqlite3.connect(db, timeout=10)` 增加等待时间。

---

## 7. 环境验证清单

完成 §1–§5 后，逐项确认：

- [ ] `python --version` ≥ 3.11
- [ ] `sqlite3.sqlite_version` ≥ 3.34
- [ ] `sqlite3_compileoption_used('ENABLE_FTS5')` 返回 1
- [ ] `pip list | grep paddleocr` 有输出（或已装 tesseract）
- [ ] `pip list | grep openai-agents` 有输出
- [ ] `sqlite3 app/db/vuln.db ".tables"` 显示 7 张表
- [ ] `SELECT COUNT(*) FROM v_type_catalog` == 10
- [ ] FTS5 触发器验证通过（§5.1 的插入测试）
- [ ] `python tests/fixtures/build_fixtures.py` 无报错
- [ ] `pytest tests/ -v` 全部通过
- [ ] `.env` 已配置且未入库
- [ ] `app/db/vuln.db`、`data/`、`tests/fixtures/pdfs/` 已在 `.gitignore` 中

全部确认后，可以开始 Phase 0。

---

## 8. 参照机记录

E-E2E-001、E-E2E-002、E-INC-006 等耗时指标需要参照机配置。首次环境搭建后，填写以下信息到 `tests/eval/reference_machine.md`：

```markdown
## 参照机 · 2026-11-08
- CPU: Intel i7-12700 / 12 核 20 线程
- 内存: 32 GB
- 磁盘: NVMe SSD
- 操作系统: Ubuntu 22.04
- Python: 3.11.9
- SQLite: 3.45.1
- OCR: PaddleOCR 2.9.1 (CPU)
- GPU: 无
- 是否启用 MinerU: 否（使用 pdfplumber）
```

**若参照机变更**，在 `tests/eval/reports/` 的历史报告中标注"参照机变更"，避免跨机器比较耗时数据。