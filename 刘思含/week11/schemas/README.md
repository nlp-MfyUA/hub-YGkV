# ChatBI-Vuln · 可执行契约（Schemas）

> **文档定位**：把四份主文档中的数据结构落成**机器可验证的文件**。AI 写代码时"对着文档看"容易漏字段、拼错名、写错类型；JSON Schema 让这些问题在单测阶段被捕获。
>
> **与 02_technical_design.md §1 的关系**：§1 是"人读的契约"，本文档是"机器读的契约"。两者必须保持一致，任何一方的改动都要同步另一方（见 00_README §7）。

---

## 1. 为什么用 JSON Schema 而不是 Pydantic

两者都能做数据校验，选择 JSON Schema 的理由：

| 维度 | JSON Schema | Pydantic |
|---|---|---|
| 跨语言 | ✅ 通用 | ❌ Python 生态 |
| 可读性 | ✅ 声明式 | 中 |
| CSV 校验 | ✅ 可用 `jsonschema` 扩展 | ❌ 需额外工具 |
| 与 `dataclass` 集成 | ✅ `pydantic.dataclasses` 可转换 | ✅ 原生 |
| 与前端共享 | ✅ 前端可直接使用 | ❌ |

**决策**：MVP 用 `dataclass` 定义结构，用 JSON Schema 做校验。两者字段名必须严格一致。

**辅助工具**：`pipeline/common/types.py` 中可用 `dataclasses.asdict()` + `jsonschema.validate()` 做双向校验（见 §4）。

---

## 2. Schema 清单

| 文件 | 校验对象 | 出现位置 |
|---|---|---|
| `canonical_vuln_record.schema.json` | `canonical_records.json` 的每个元素 | Phase 2 → 3 契约 |
| `image_record.schema.json` | `image_records.json` 的每个元素 | Phase 2 → 3 契约 |
| `retest_record.schema.json` | `retest_records.json` 的每个元素 | Phase 2 → 3 契约 |
| `corpus_profile.schema.json` | `corpus_profile.json` | Phase 1 → 2 契约 |
| `processing_plan.schema.json` | `ProcessingPlan` 的 JSON 序列化 | Phase 5 输出 |
| `pipeline_eval.schema.json` | `pipeline_eval.csv` 的列 | 评测集 |
| `image_eval.schema.json` | `image_eval.csv` 的列 | 评测集 |
| `chat_eval.schema.json` | `chat_eval.csv` 的列 | 评测集 |

---

## 3. Schema 定义

### 3.1 `canonical_vuln_record.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "canonical_vuln_record.schema.json",
  "title": "CanonicalVulnRecord",
  "type": "object",
  "additionalProperties": false,
  "required": ["vuln_name", "severity_raw", "source_file", "instance_index", "extraction_method", "confidence"],
  "properties": {
    "vuln_name": { "type": "string", "minLength": 1 },
    "severity_raw": { "type": "string", "minLength": 1 },
    "source_file": { "type": "string", "minLength": 1 },
    "source_page": { "type": ["integer", "null"], "minimum": 1 },
    "instance_index": { "type": "integer", "minimum": 1 },
    "type_raw": { "type": ["string", "null"] },
    "cvss_score": { "type": ["number", "null"], "minimum": 0, "maximum": 10 },
    "component": { "type": ["string", "null"] },
    "cwe_id": { "type": ["string", "null"], "pattern": "^CWE-\\d+$" },
    "description_snippet": { "type": ["string", "null"], "maxLength": 303 },
    "extraction_method": { "type": "string", "enum": ["table_row", "kv_block", "text_block"] },
    "confidence": { "type": "string", "enum": ["high", "medium", "low"] }
  }
}
```

**说明**：`description_snippet` 的 `maxLength: 303` 是 300 字符 + 3 字符的 `"..."`。

### 3.2 `image_record.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "image_record.schema.json",
  "title": "ImageRecord",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "source_file", "source_page", "image_index", "image_path",
    "image_type", "ocr_text", "ocr_confidence", "linked_vuln_name"
  ],
  "properties": {
    "source_file": { "type": "string", "minLength": 1 },
    "source_page": { "type": "integer", "minimum": 1 },
    "image_index": { "type": "integer", "minimum": 0 },
    "image_path": {
      "type": "string",
      "pattern": "^[^/\\\\].*\\.(png|jpg|jpeg)$",
      "not": { "pattern": "^(/|[A-Za-z]:)" }
    },
    "image_type": { "type": "string", "enum": ["screenshot", "chart", "unknown"] },
    "ocr_text": { "type": "string" },
    "ocr_confidence": { "type": "string", "enum": ["high", "medium", "low"] },
    "linked_vuln_name": { "type": ["string", "null"] },
    "generated_description": { "type": "null" }
  }
}
```

**说明**：
- `image_path` 的 `not` 约束排除了绝对路径（C-IMG-003）；
- `generated_description` 的类型固定为 `null`（D-004，MVP 恒为 None）。

### 3.3 `corpus_profile.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "corpus_profile.schema.json",
  "title": "CorpusProfile",
  "type": "object",
  "required": ["schema_version", "parse_strategy", "image_strategy", "approved"],
  "properties": {
    "schema_version": { "type": "string", "enum": ["1.0"] },
    "sample_files": { "type": "array", "items": { "type": "string" } },
    "page_count_range": {
      "type": "array", "items": { "type": "integer", "minimum": 1 }, "minItems": 2, "maxItems": 2
    },
    "is_scanned_ratio": { "type": "number", "minimum": 0, "maximum": 1 },
    "template_groups": { "type": "array" },
    "header_aliases_observed": { "type": "object" },
    "severity_vocabulary": { "type": "array", "items": { "type": "string" } },
    "has_summary_count_table": { "type": "boolean" },
    "tables_span_pages": { "type": "boolean" },
    "image_stats": { "type": "object" },
    "parse_strategy": {
      "type": "object",
      "required": ["primary_adapter", "fallback_adapter", "vlm_description_enabled"],
      "properties": {
        "primary_adapter": { "type": "string", "enum": ["mineru", "pdfplumber"] },
        "fallback_adapter": { "type": "string", "enum": ["mineru", "pdfplumber"] },
        "kv_fallback_enabled": { "type": "boolean" },
        "vlm_description_enabled": { "type": "boolean", "const": false }
      }
    },
    "image_strategy": {
      "type": "object",
      "required": ["ocr_enabled", "vlm_description_enabled"],
      "properties": {
        "ocr_enabled": { "type": "boolean" },
        "ocr_engine": { "type": "string", "enum": ["paddleocr", "tesseract", "mineru_builtin"] },
        "ocr_languages": { "type": "array", "items": { "type": "string" } },
        "link_by_page_proximity": { "type": "boolean" },
        "link_page_window": { "type": "integer", "minimum": 0, "maximum": 5 },
        "vlm_description_enabled": { "type": "boolean", "const": false }
      }
    },
    "approved": { "type": "boolean" },
    "approved_by": { "type": ["string", "null"] },
    "approved_at": { "type": ["string", "null"], "format": "date-time" }
  }
}
```

**关键约束**：
- `vlm_description_enabled` 在两个位置都 `const: false`（C-IMG-001 的 schema 级保障）；
- `parse_strategy` 和 `image_strategy` 都必须含 `vlm_description_enabled: false`，否则校验失败。

### 3.4 `processing_plan.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "processing_plan.schema.json",
  "title": "ProcessingPlan",
  "type": "object",
  "required": ["items", "skipped_count", "generated_at", "pipeline_version"],
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["relative_path", "action", "reason"],
        "properties": {
          "relative_path": { "type": "string", "minLength": 1 },
          "action": { "type": "string", "enum": ["new", "content_changed", "logic_changed", "orphan"] },
          "reason": { "type": "string", "minLength": 1 },
          "current_hash": { "type": ["string", "null"], "pattern": "^[a-f0-9]{64}$" },
          "indexed_hash": { "type": ["string", "null"], "pattern": "^[a-f0-9]{64}$" }
        }
      }
    },
    "skipped_count": { "type": "integer", "minimum": 0 },
    "generated_at": { "type": "string", "format": "date-time" },
    "pipeline_version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" }
  }
}
```

### 3.5 `pipeline_eval.schema.json`

CSV 不适合 JSON Schema，用**列定义文件**：

```json
{
  "type": "csv",
  "columns": [
    {"name": "relative_path", "type": "string", "required": true},
    {"name": "expected_vuln_count", "type": "integer", "required": true, "min": 0},
    {"name": "expected_severity_dist", "type": "string", "required": true, "pattern": "^(高危|中危|低危|信息):\\d+(;(高危|中危|低危|信息):\\d+)*$"},
    {"name": "expected_type_dist", "type": "string", "required": false},
    {"name": "expected_image_count", "type": "integer", "required": false, "min": -1},
    {"name": "has_summary_table", "type": "boolean", "required": true},
    {"name": "notes", "type": "string", "required": false},
    {"name": "annotated_by", "type": "string", "required": true},
    {"name": "annotated_at", "type": "string", "required": true, "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}
  ]
}
```

### 3.6 `image_eval.schema.json`

```json
{
  "type": "csv",
  "columns": [
    {"name": "id", "type": "string", "required": true, "pattern": "^IMG-\\d{3}$"},
    {"name": "relative_path", "type": "string", "required": true},
    {"name": "question", "type": "string", "required": true},
    {"name": "expected_ocr_keywords", "type": "string", "required": true},
    {"name": "expected_image_path", "type": "string", "required": true},
    {"name": "category", "type": "string", "required": true, "enum": ["payload", "response", "request_path", "error_message", "injection_attack", "negative_case"]},
    {"name": "notes", "type": "string", "required": false},
    {"name": "annotated_by", "type": "string", "required": true},
    {"name": "annotated_at", "type": "string", "required": true, "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}
  ]
}
```

### 3.7 `chat_eval.schema.json`

```json
{
  "type": "csv",
  "columns": [
    {"name": "id", "type": "string", "required": true, "pattern": "^CHAT-\\d{3}$"},
    {"name": "question", "type": "string", "required": true},
    {"name": "expected_answer_type", "type": "string", "required": true, "enum": ["number", "list", "ranking", "refusal", "clarification"]},
    {"name": "expected_value", "type": "string", "required": true},
    {"name": "expected_sql_contains", "type": "string", "required": false},
    {"name": "category", "type": "string", "required": true, "enum": ["count", "distribution", "comparison", "ranking", "multi_turn", "negative_case"]},
    {"name": "notes", "type": "string", "required": false},
    {"name": "annotated_by", "type": "string", "required": true},
    {"name": "annotated_at", "type": "string", "required": true, "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}
  ]
}
```

### 3.8 `retest_record.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "retest_record.schema.json",
  "title": "RetestRecord",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "retest_report_path", "raw_vuln_name", "component",
    "retest_status_raw", "retest_status", "retest_date",
    "evidence_snippet", "source_page", "instance_index",
    "parent_vuln_name", "match_confidence"
  ],
  "properties": {
    "retest_report_path": { "type": "string", "minLength": 1 },
    "raw_vuln_name": { "type": "string", "minLength": 1 },
    "component": { "type": ["string", "null"] },
    "retest_status_raw": { "type": "string" },
    "retest_status": {
      "type": "string",
      "enum": ["fixed", "unfixed", "partial", "not_reproducible", "unknown"]
    },
    "retest_date": { "type": ["string", "null"] },
    "evidence_snippet": { "type": ["string", "null"], "maxLength": 300 },
    "source_page": { "type": ["integer", "null"], "minimum": 1 },
    "instance_index": { "type": "integer", "minimum": 1 },
    "evidence_page": { "type": ["integer", "null"], "minimum": 1 },
    "parent_vuln_name": { "type": ["string", "null"] },
    "match_confidence": {
      "type": "string",
      "enum": ["exact", "fuzzy", "none"]
    }
  }
}
```

**说明**：`retest_status` 与 `app/db/schema.sql` 的 CHECK 一致；`additionalProperties: false` 保证回归记录不会混入 `CanonicalVulnRecord` 字段。

---

## 4. 校验方式

### 4.1 单测校验（JSON）

```python
import json
from jsonschema import validate
from pathlib import Path

def load_schema(name: str) -> dict:
    return json.loads((Path("schemas") / f"{name}.schema.json").read_text())

def test_canonical_records_match_schema():
    schema = load_schema("canonical_vuln_record")
    records = json.loads(Path("data/parsed_output/xxx/latest/canonical_records.json").read_text())
    for r in records:
        validate(instance=r, schema=schema)
```

### 4.2 CI 校验（CSV）

```python
import csv
import re

def validate_csv(csv_path: Path, schema: dict) -> list[str]:
    errors = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        for col in schema["columns"]:
            if col.get("required") and col["name"] not in header:
                errors.append(f"missing required column: {col['name']}")
        for row_idx, row in enumerate(reader, start=2):
            for col in schema["columns"]:
                val = row.get(col["name"], "")
                if col.get("required") and not val:
                    errors.append(f"row {row_idx}: {col['name']} is empty")
                if "pattern" in col and val and not re.match(col["pattern"], val):
                    errors.append(f"row {row_idx}: {col['name']} = {val!r} doesn't match {col['pattern']}")
    return errors
```

### 4.3 与 dataclass 的双向校验

```python
# pipeline/common/types.py
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from jsonschema import validate

@dataclass(frozen=True)
class CanonicalVulnRecord:
    ...
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalVulnRecord":
        _validate(d, "canonical_vuln_record")
        return cls(**d)

_SCHEMA_CACHE: dict[str, dict] = {}

def _validate(instance: dict, schema_name: str) -> None:
    if schema_name not in _SCHEMA_CACHE:
        path = Path("schemas") / f"{schema_name}.schema.json"
        _SCHEMA_CACHE[schema_name] = json.loads(path.read_text())
    validate(instance=instance, schema=_SCHEMA_CACHE[schema_name])
```

**注意**：`from_dict` 与 `to_dict` 必须都能通过 schema 校验，这是 C-CTR-003 的实现基础。

---

## 5. Schema 变更流程

1. **先改文档**：修改 `02_technical_design.md` §1 的对应章节；
2. **改 schema 文件**：同步 `schemas/*.schema.json`；
3. **改 dataclass**：同步 `pipeline/common/types.py`；
4. **跑一致性测试**：`pytest tests/test_c_ctr_003.py`；
5. **PR 中说明**：变更影响了哪些下游模块、是否需要迁移已入库数据。

**禁止**：只改 schema 不改文档，或只改 dataclass 不改 schema。三者必须同步。

---

## 6. 与 03_constraints 的对应

| Schema 约束 | 对应 C-ID |
|---|---|
| `vlm_description_enabled: const false` | C-IMG-001 |
| `image_path` 禁止绝对路径 | C-IMG-003 |
| `CanonicalVulnRecord` 字段名与 02 §1.1 一致 | C-CTR-012 |
| `RetestRecord` 字段名与 02 §1.3 一致 | C-CTR-012 |
| CSV 的 `category` 枚举 | 04 §1.2 / §1.3 |
| `generated_description: null` | C-CTR-005 |