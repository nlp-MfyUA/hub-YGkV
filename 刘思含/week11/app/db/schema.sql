PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS v_report (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_name     TEXT    NOT NULL,
    test_date       TEXT,
    target_system   TEXT,
    tester          TEXT,
    status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','orphaned')),
    report_type     TEXT    NOT NULL DEFAULT 'pentest'
                    CHECK(report_type IN ('pentest','retest')),
    parent_report_id INTEGER REFERENCES v_report(id),
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE(report_name)
);

CREATE INDEX IF NOT EXISTS ix_report_type ON v_report(report_type);
CREATE INDEX IF NOT EXISTS ix_report_parent ON v_report(parent_report_id);

CREATE TABLE IF NOT EXISTS v_vulnerability (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       INTEGER NOT NULL REFERENCES v_report(id) ON DELETE CASCADE,
    source_file     TEXT    NOT NULL,
    vuln_name       TEXT    NOT NULL,
    severity        TEXT    NOT NULL CHECK(severity IN ('高危','中危','低危','信息')),
    severity_raw    TEXT    NOT NULL,
    type_code       TEXT    NOT NULL,
    type_name       TEXT    NOT NULL,
    cvss_score      REAL,
    component       TEXT,
    cwe_id          TEXT,
    description_snippet TEXT CHECK(description_snippet IS NULL OR length(description_snippet) <= 303),
    source_page     INTEGER,
    instance_index  INTEGER NOT NULL DEFAULT 1,
    extraction_method TEXT  NOT NULL,
    confidence      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','superseded','orphaned')),
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

-- MVP 采用"入库前将 component=None 统一转为 ''"的方案，避免 NULL 参与唯一性
CREATE UNIQUE INDEX IF NOT EXISTS ux_vuln_file_name_component
    ON v_vulnerability(source_file, vuln_name, component, instance_index);

CREATE INDEX IF NOT EXISTS ix_vuln_name_component
    ON v_vulnerability(report_id, vuln_name, component);

CREATE INDEX IF NOT EXISTS ix_vuln_severity  ON v_vulnerability(severity);
CREATE INDEX IF NOT EXISTS ix_vuln_type_code ON v_vulnerability(type_code);
CREATE INDEX IF NOT EXISTS ix_vuln_source    ON v_vulnerability(source_file);

-- ★ 新增：回归报告复测结果（方案 B）
CREATE TABLE IF NOT EXISTS v_retest_result (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    vuln_id           INTEGER REFERENCES v_vulnerability(id) ON DELETE CASCADE,
    retest_report_id  INTEGER NOT NULL REFERENCES v_report(id) ON DELETE CASCADE,
    raw_vuln_name     TEXT    NOT NULL,
    component         TEXT,
    retest_status     TEXT    NOT NULL DEFAULT 'unknown'
                      CHECK(retest_status IN ('fixed','unfixed','partial','not_reproducible','unknown')),
    retest_status_raw TEXT,
    retest_date       TEXT,
    evidence_snippet  TEXT,
    source_page       INTEGER,
    instance_index    INTEGER NOT NULL DEFAULT 1,
    evidence_page     INTEGER,
    match_confidence  TEXT    NOT NULL DEFAULT 'none'
                      CHECK(match_confidence IN ('exact','fuzzy','none')),
    status            TEXT    NOT NULL DEFAULT 'active'
                      CHECK(status IN ('active','superseded','orphaned')),
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);

-- 与 v_vulnerability 一致：入库前 component=None 转为空字符串；
-- ON CONFLICT(retest_report_id, raw_vuln_name, component) 直接引用列名，不使用表达式。
CREATE UNIQUE INDEX IF NOT EXISTS ux_retest_report_name_component
    ON v_retest_result(retest_report_id, raw_vuln_name, component, instance_index);

CREATE INDEX IF NOT EXISTS ix_retest_vuln   ON v_retest_result(vuln_id);
CREATE INDEX IF NOT EXISTS ix_retest_report ON v_retest_result(retest_report_id);
CREATE INDEX IF NOT EXISTS ix_retest_status ON v_retest_result(retest_status);
CREATE INDEX IF NOT EXISTS ix_retest_match  ON v_retest_result(match_confidence);

CREATE TABLE IF NOT EXISTS v_type_catalog (
    type_code   TEXT PRIMARY KEY,
    type_name   TEXT NOT NULL,
    category    TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS kb_entry (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    question_pattern TEXT    NOT NULL,
    sql_template     TEXT    NOT NULL,
    params_schema    TEXT,
    term             TEXT,
    definition       TEXT,
    status           TEXT    NOT NULL DEFAULT 'pending'
                     CHECK(status IN ('pending','approved','rejected')),
    hit_count        INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL
);

-- ★ 新增：图片证据表
CREATE TABLE IF NOT EXISTS v_image_evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       INTEGER NOT NULL REFERENCES v_report(id) ON DELETE CASCADE,
    source_file     TEXT    NOT NULL,
    source_page     INTEGER NOT NULL,
    image_index     INTEGER NOT NULL,
    image_path      TEXT    NOT NULL,
    image_type      TEXT    NOT NULL DEFAULT 'unknown'
                    CHECK(image_type IN ('screenshot','chart','unknown')),
    ocr_text        TEXT    NOT NULL DEFAULT '',
    ocr_confidence  TEXT    NOT NULL DEFAULT 'medium'
                    CHECK(ocr_confidence IN ('high','medium','low')),
    linked_vuln_name TEXT,
    generated_description TEXT CHECK(generated_description IS NULL),
    status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','superseded','orphaned')),
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE(source_file, source_page, image_index)
);

CREATE INDEX IF NOT EXISTS ix_image_source     ON v_image_evidence(source_file);
CREATE INDEX IF NOT EXISTS ix_image_vuln_name  ON v_image_evidence(linked_vuln_name);

-- ★ 新增：FTS5 全文索引（trigram 分词，对中英文混合更友好）
CREATE VIRTUAL TABLE IF NOT EXISTS v_image_evidence_fts USING fts5(
    ocr_text,
    linked_vuln_name,
    content='v_image_evidence',
    content_rowid='id',
    tokenize='trigram'
);

-- FTS5 同步触发器
CREATE TRIGGER IF NOT EXISTS trg_image_ai AFTER INSERT ON v_image_evidence BEGIN
    INSERT INTO v_image_evidence_fts(rowid, ocr_text, linked_vuln_name)
    VALUES (new.id, new.ocr_text, new.linked_vuln_name);
END;

CREATE TRIGGER IF NOT EXISTS trg_image_ad AFTER DELETE ON v_image_evidence BEGIN
    INSERT INTO v_image_evidence_fts(v_image_evidence_fts, rowid, ocr_text, linked_vuln_name)
    VALUES ('delete', old.id, old.ocr_text, old.linked_vuln_name);
END;

CREATE TRIGGER IF NOT EXISTS trg_image_au AFTER UPDATE ON v_image_evidence BEGIN
    INSERT INTO v_image_evidence_fts(v_image_evidence_fts, rowid, ocr_text, linked_vuln_name)
    VALUES ('delete', old.id, old.ocr_text, old.linked_vuln_name);
    INSERT INTO v_image_evidence_fts(rowid, ocr_text, linked_vuln_name)
    VALUES (new.id, new.ocr_text, new.linked_vuln_name);
END;

CREATE TABLE IF NOT EXISTS pdf_index (
    relative_path    TEXT PRIMARY KEY,
    file_size        INTEGER NOT NULL,
    mtime_ns         INTEGER NOT NULL,
    content_hash     TEXT    NOT NULL,
    parser_name      TEXT    NOT NULL,
    parser_version   TEXT    NOT NULL,
    pipeline_version TEXT    NOT NULL,
    parse_status     TEXT    NOT NULL
                     CHECK(parse_status IN ('pass','pending_review','fail','no_vulnerabilities')),
    load_status      TEXT    NOT NULL
                     CHECK(load_status IN ('pass','fail','orphaned','skipped_no_vulns')),
    last_processed_at TEXT   NOT NULL,
    last_batch_id    TEXT
);

INSERT OR IGNORE INTO v_type_catalog(type_code, type_name, category) VALUES
    ('SQLI','SQL 注入','注入类'), ('XSS','跨站脚本','注入类'),
    ('RCE','远程代码执行','执行类'), ('LFI','本地文件包含','文件类'),
    ('SSRF','服务端请求伪造','请求类'), ('CSRF','跨站请求伪造','请求类'),
    ('AUTH','认证/授权缺陷','认证类'), ('INFO','信息泄露','信息类'),
    ('CONFIG','配置错误','配置类'), ('UNKNOWN','待归类','待归类'),
    ('AUTHZ','越权访问','认证类'), ('LOGIC','逻辑漏洞','业务逻辑类'),
    ('UPLOAD','文件上传','文件类'), ('LEAK','敏感信息泄露','信息类'),
    ('CSP','内容安全策略缺失','配置类'), ('CAPTCHA','验证码缺陷','认证类'),
    ('DOMXSS','DOM 型 XSS','注入类'), ('BRUTE','口令爆破','认证类'),
    ('REDIRECT','开放重定向','请求类');
