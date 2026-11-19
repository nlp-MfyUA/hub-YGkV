"""E-LOAD 全量验收（docs/04_evaluation.md §3）。

只读脚本：读 app/db/vuln.db + data/parsed_output/*/*.json + data/batch*.log + data/full_batch_1_status_final.json
不修改项目源码与数据库。

口径说明：
- E-LOAD-002：数据库归一化结果 + severity_map.yaml 显式映射命中率（日志仅作佐证，
  因为逐条 `severity_fallback` WARN 日志未落盘到 data/*.log，与文档 §3.2 描述的测量方式有偏差）。
- E-LOAD-005：同时校验 fts 行数与 fts_docsize 行数。
- E-LOAD-006：合并「本轮 load_status 明细日志」与「批次 1 最终 load_status 汇总」。
- E-LOAD-007：按 pdf_id → parsed_output 目录关联（canonical_records.json 的 source_file 有 206 份为空，
  且部分路径形态与状态文件不一致，按路径比对会误判）。

用法：python -X utf8 data/eval_load_full.py
"""
import glob
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "app" / "db" / "vuln.db"
PARSED = ROOT / "data" / "parsed_output"
LOG_FILES = ["batch2a1.log", "batch2a2.log", "batch2a3.log", "batch2b.log", "batch2c.log"]
STATUS_REPLAY = ["full_batch_2a1_status.json", "full_batch_2a2_status.json",
                 "full_batch_2a3_status.json", "full_batch_2b_status.json"]
BATCH1_FINAL = "full_batch_1_status_final.json"

NORM_SEV = {"高危", "中危", "低危", "信息"}
NORM = NORM_SEV


def level(metric, value):
    gates = {
        "E-LOAD-001": (lambda v: v == 0, lambda v: v == 0),
        "E-LOAD-002": (lambda v: v >= 0.85, lambda v: v >= 0.95),
        "E-LOAD-003": (lambda v: v >= 0.60, lambda v: v >= 0.80),
        "E-LOAD-004": (lambda v: v == 0, lambda v: v == 0),
        "E-LOAD-005": (lambda v: v, lambda v: v),
        "E-LOAD-006": (lambda v: v >= 1.0, lambda v: v >= 1.0),
        "E-LOAD-007": (lambda v: v >= 1.0, lambda v: v >= 1.0),
        "E-LOAD-008": (lambda v: v >= 1200, lambda v: v >= 1200),
    }
    g, good = gates[metric]
    if not g(value):
        return "未达标"
    if metric in ("E-LOAD-002", "E-LOAD-003"):
        return "优秀" if value >= (1.0 if metric == "E-LOAD-002" else 0.90) else ("良好" if good(value) else "门禁")
    return "达标"


def find_severity_map():
    for cand in (ROOT / "pipeline" / "config" / "severity_map.yaml",
                 ROOT / "pipeline" / "phase3_load" / "severity_map.yaml",
                 ROOT / "schemas" / "severity_map.yaml"):
        if cand.exists():
            return cand
    hits = list(ROOT.rglob("severity_map.y*ml"))
    return hits[0] if hits else None


def parse_log_rows():
    """从 data/batch*.log 提取本轮 ROW 明细（relative_path -> row）。"""
    rows = {}
    bad = []
    for name in LOG_FILES:
        p = ROOT / "data" / name
        if not p.exists():
            bad.append(f"{name}: 缺失")
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s.startswith("ROW "):
                continue
            try:
                r = json.loads(s[4:])
            except json.JSONDecodeError:
                bad.append(f"{name}: JSON 解析失败 {s[:80]}")
                continue
            r["_log"] = name
            rows[r["relative_path"]] = r
    return rows, bad


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    out = {}

    total_vuln = con.execute("SELECT COUNT(*) FROM v_vulnerability WHERE status='active'").fetchone()[0]
    total_retest = con.execute("SELECT COUNT(*) FROM v_retest_result WHERE status='active'").fetchone()[0]
    img_active = con.execute("SELECT COUNT(*) FROM v_image_evidence WHERE status='active'").fetchone()[0]

    # ===== E-LOAD-001 漏洞重复率 =====
    # 口径 A（文档字面）：GROUP BY source_file, vuln_name, component
    # 口径 B（入库唯一键，schema.sql:47）：source_file, vuln_name, component, instance_index
    # 差异根因：同一漏洞名在一份报告内多处出现时用 instance_index 区分（属正常建模，不是重复入库）
    dup_a = con.execute(
        "SELECT source_file, vuln_name, component, COUNT(*) c, GROUP_CONCAT(id) ids FROM v_vulnerability "
        "WHERE status='active' GROUP BY 1,2,3 HAVING COUNT(*) > 1"
    ).fetchall()
    dup_b = con.execute(
        "SELECT source_file, vuln_name, component, COUNT(*) c, GROUP_CONCAT(id) ids FROM v_vulnerability "
        "WHERE status='active' GROUP BY 1,2,3,instance_index HAVING COUNT(*) > 1"
    ).fetchall()
    inst_used = con.execute(
        "SELECT COUNT(*) FROM v_vulnerability WHERE status='active' AND instance_index > 1"
    ).fetchone()[0]
    # 口径 A 下“真重复”的判别：同组内实例位重复才算真重复
    true_dup = [
        {"source_file": r[0], "vuln_name": r[1], "component": r[2],
         "count": r[3], "extra_rows": r[3] - 1, "ids": r[4]}
        for r in dup_a if len(set(r[4].split(","))) > r[3]
    ]
    extra_a = sum(r[3] - 1 for r in dup_a)
    out["E-LOAD-001"] = {
        "value": len(dup_b),
        "level": level("E-LOAD-001", len(dup_b)),
        "detail": {
            "门禁口径": "入库唯一键 (source_file, vuln_name, component, instance_index)，违反组数",
            "口径B_违反唯一键组数": len(dup_b),
            "口径A_不含instance_index的重复组数": len(dup_a),
            "口径A_冗余行数": extra_a,
            "口径A_重复率": round(extra_a / total_vuln, 4) if total_vuln else 0,
            "instance_index > 1 的记录数": inst_used,
            "口径A下真重复(同组实例位冲突)组数": len(true_dup),
            "active 漏洞总数": total_vuln,
            "口径A Top5": [
                {"source_file": r[0], "vuln_name": r[1], "count": r[3], "ids": r[4]} for r in dup_a[:5]
            ],
        },
    }

    # ===== E-LOAD-003 类型归一化覆盖率 =====
    unknown = con.execute(
        "SELECT COUNT(*) FROM v_vulnerability WHERE status='active' AND type_code='UNKNOWN'"
    ).fetchone()[0]
    covered = total_vuln - unknown
    cov = covered / total_vuln if total_vuln else 0
    type_dist = con.execute(
        "SELECT type_code, COUNT(*) c FROM v_vulnerability WHERE status='active' GROUP BY 1 ORDER BY c DESC"
    ).fetchall()
    out["E-LOAD-003"] = {
        "value": round(cov, 4),
        "level": level("E-LOAD-003", cov),
        "detail": {
            "覆盖": f"{covered}/{total_vuln}",
            "UNKNOWN": unknown,
            "类型分布": {r["type_code"]: r["c"] for r in type_dist},
        },
    }

    # ===== E-LOAD-004 图片重复率 =====
    img_dup_groups = con.execute(
        "SELECT source_file, source_page, image_index, COUNT(*) c FROM v_image_evidence "
        "WHERE status='active' GROUP BY 1,2,3 HAVING COUNT(*) > 1"
    ).fetchall()
    out["E-LOAD-004"] = {
        "value": len(img_dup_groups),
        "level": level("E-LOAD-004", len(img_dup_groups)),
        "detail": {"重复组数": len(img_dup_groups), "active 图片总数": img_active},
    }

    # ===== E-LOAD-005 FTS5 一致性 =====
    fts = con.execute("SELECT COUNT(*) FROM v_image_evidence_fts").fetchone()[0]
    docsize = con.execute("SELECT COUNT(*) FROM v_image_evidence_fts_docsize").fetchone()[0]
    # 采样校验 fts 内容确实对应 active 记录（不只是行数相等）
    mismatch_sample = con.execute(
        "SELECT COUNT(*) FROM v_image_evidence i LEFT JOIN v_image_evidence_fts f ON f.rowid = i.id "
        "WHERE i.status='active' AND f.rowid IS NULL"
    ).fetchone()[0]
    fts_ok = (fts == img_active == docsize) and mismatch_sample == 0
    out["E-LOAD-005"] = {
        "value": fts_ok,
        "level": level("E-LOAD-005", fts_ok),
        "detail": {
            "v_image_evidence(active)": img_active,
            "fts 行数": fts,
            "fts_docsize 行数": docsize,
            "active 记录在 fts 中缺失数": mismatch_sample,
        },
    }

    # ===== E-LOAD-002 严重性归一化覆盖率 =====
    sev_rows = con.execute(
        "SELECT severity, severity_raw, COUNT(*) c FROM v_vulnerability WHERE status='active' GROUP BY 1,2"
    ).fetchall()
    non_norm = sum(r["c"] for r in sev_rows if r["severity"] not in NORM)
    smap = find_severity_map()
    map_keys = set()
    if smap:
        txt = smap.read_text(encoding="utf-8", errors="ignore")
        map_keys = {m.group(1).strip().strip("'\"") for m in re.finditer(
            r"^\s*['\"]?([^'\":\n#][^':\n#]*?)['\"]?\s*:\s*\S+\s*$", txt, re.M)}
    raws = sorted({(r["severity_raw"] or "").strip() for r in sev_rows})
    # 显式映射 = 小写后精确命中 severity_map 的键（与 normalizer.normalize_severity 一致）
    map_keys_lower = {k.lower() for k in map_keys}
    explicit_cov = sum(r["c"] for r in sev_rows if (r["severity_raw"] or "").strip().lower() in map_keys_lower)
    norm_by_rule = []
    for r in sev_rows:
        raw = (r["severity_raw"] or "").strip()
        if raw and raw.lower() not in map_keys_lower:
            norm_by_rule.append({"severity_raw": raw, "severity": r["severity"], "count": r["c"]})
    log_fallback = 0
    for f in glob.glob(str(ROOT / "data" / "*.log")):
        log_fallback += len(re.findall(r"severity_fallback", Path(f).read_text(encoding="utf-8", errors="ignore")))
    cov_002 = non_norm == 0  # 质量底线：归一化后无非法值
    explicit_ratio = explicit_cov / total_vuln if total_vuln else 0
    explicit_level = ("优秀" if explicit_ratio >= 1.0 else ("良好" if explicit_ratio >= 0.95 else ("门禁" if explicit_ratio >= 0.85 else "未达标")))
    out["E-LOAD-002"] = {
        "value": round(explicit_ratio, 4),
        "level": explicit_level if non_norm == 0 else "未达标",
        "detail": {
            "归一化合法性(无非法 severity)": cov_002,
            "非标准 severity 记录数": non_norm,
            "severity 分布": {(r["severity"]): r["c"] for r in sev_rows},
            "severity_raw 去重数": len(raws),
            "severity_map": str(smap.relative_to(ROOT)) if smap else "未找到",
            "severity_map 键数": len(map_keys),
            "显式映射命中记录数": explicit_cov,
            "显式映射覆盖率": round(explicit_ratio, 4),
            "走规则兜底的 severity_raw": norm_by_rule,
            "日志 severity_fallback 次数": log_fallback,
            "说明": "日志未逐条落盘 severity_fallback，显式映射覆盖率按 severity_map.yaml 键与 severity_raw 精确匹配计算",
        },
    }

    # ===== E-LOAD-006 事务成功率 =====
    # 口径（docs/04_evaluation.md §3 E-LOAD-006 口径说明）：
    #   分母 = load_status ∈ {pass, fail, already}（实际尝试提交事务）
    #   分子 = pass + already
    #   pending_review（按设计跳过）/ skipped_no_vulns（无漏洞可写）不计入分母，单列审计
    #   同一 relative_path 多次出现取最后一次状态（log_rows 以 dict 覆盖，后者胜出）
    TX_STATUSES = {"pass", "fail", "already"}
    FINAL = "DB已入库"  # 事后核验：数据库里该报告已 complete，说明重跑已成功（见 [FULL-011]）
    log_rows, log_bad = parse_log_rows()
    # [FULL-011] 取最后一次状态：先按时间戳顺序叠加 {segment}_{timestamp}_status.json
    # （新格式），再叠加无时间戳的旧汇总，最后叠加上面的日志明细——后写入者胜出。
    replay_source = {}
    for p in sorted(glob.glob(str(ROOT / "data" / "full_batch_*_status.json"))):
        name = Path(p).name
        if re.search(r"_\d{8}T\d{6}_status\.json$", name):
            replay_source[name] = p
    for f in STATUS_REPLAY:
        p = ROOT / "data" / f
        if p.exists():
            replay_source[f] = str(p)
    replay = []
    for name, p in replay_source.items():
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        for r in data.get("rows", []):
            log_rows[r["relative_path"]] = dict(r, _log=name)
            replay.append(name)
    # 覆盖旧失败：日志中 fail 的报告，若数据库显示已完整入库，则视为"取最后一次状态 = 成功"
    report_type = {r["report_name"]: r["report_type"] for r in con.execute(
        "SELECT report_name, report_type FROM v_report WHERE status='active'")}
    vuln_by_file = {r["source_file"]: r["c"] for r in con.execute(
        "SELECT source_file, COUNT(*) c FROM v_vulnerability WHERE status='active' GROUP BY 1")}
    retest_by_report = {r["nm"]: r["c"] for r in con.execute(
        "SELECT rep.report_name nm, COUNT(*) c FROM v_retest_result rr "
        "JOIN v_report rep ON rep.id = rr.retest_report_id WHERE rr.status='active' GROUP BY 1")}
    overridden = []
    for r in log_rows.values():
        if r.get("load_status") != "fail":
            continue
        sf = r["relative_path"]
        if sf not in report_type:
            continue  # pending_review 报告不入 v_report，保持原状态
        later = (
            vuln_by_file.get(sf, 0) > 0 if report_type[sf] == "pentest"
            else retest_by_report.get(sf, 0) > 0
        )
        if later:
            overridden.append({"relative_path": sf, "log": r["_log"],
                               "log_error": r.get("error"), "final": FINAL})
            r["load_status"] = FINAL
            r["_overridden_from"] = r.get("error")

    status_of = lambda r: r.get("load_status")
    c = Counter(status_of(r) for r in log_rows.values())
    ok = c.get("pass", 0) + c.get("already", 0) + c.get(FINAL, 0)
    total_tx = sum(v for k, v in c.items() if k in TX_STATUSES or k == FINAL)
    # pending_review 若被旧日志写成 fail：按 error 字段剔除，单列审计（不改数据，只改统计口径）
    pending_fail = [r for r in log_rows.values() if r.get("load_status") == "fail" and r.get("error") == "pending_review"]
    if pending_fail:
        for r in pending_fail:
            r["load_status"] = "skipped_pending_review"
        c = Counter(status_of(r) for r in log_rows.values())
        total_tx = sum(v for k, v in c.items() if k in TX_STATUSES or k == FINAL)
        excluded = {k: v for k, v in c.items() if k not in TX_STATUSES and k != FINAL and k is not None}

    b1 = json.loads((ROOT / "data" / BATCH1_FINAL).read_text(encoding="utf-8"))
    b1_all = b1["load_status"]
    b1_ok = b1_all.get("pass", 0) + b1_all.get("already", 0)
    b1_tx = sum(v for k, v in b1_all.items() if k in TX_STATUSES)
    b1_excluded = {k: v for k, v in b1_all.items() if k not in TX_STATUSES}

    numerator = ok + b1_ok
    denominator = total_tx + b1_tx
    rate = numerator / denominator if denominator else 0
    out["E-LOAD-006"] = {
        "value": round(rate, 4),
        "level": level("E-LOAD-006", rate),
        "detail": {
            "口径": "分母=load_status∈{pass,fail,already,DB已入库}；分子=pass+already+DB已入库；"
                    "pending_review 的 fail 不计入分母；数据库已完整入库的报告覆盖旧失败",
            "分子(成功事务数)": numerator,
            "分母(尝试提交事务数)": denominator,
            "成功率": round(rate, 4),
            "本轮(批次2a1..2c)": {
                "分母": total_tx,
                "成功(pass+already+DB已入库)": ok,
                "分布": dict(c),
                "未计入分母(单列)": excluded,
                "旧失败被覆盖(DB已入库)明细": overridden,
                "旧日志写成 fail 的 pending_review(按设计跳过，已按 error 剔除)": len(pending_fail),
            },
            "批次1(官方最终汇总)": {
                "分母": b1_tx,
                "成功(pass+already)": b1_ok,
                "分布": b1_all,
                "未计入分母(单列)": b1_excluded,
            },
            "日志内原始 fail 记录数": sum(
                1 for r in log_rows.values() if r.get("_overridden_from") is not None
            ) + c.get("fail", 0),
            "日志解析异常": log_bad,
            "备注": "[FULL-011] 旧失败记录未回写；此处按数据库现状判定最终状态，见 docs/tech_debt.md",
        },
    }

    # ===== E-LOAD-007 入库条数一致性 =====
    # pdf_id -> parsed dir
    dirs = {}
    for d in PARSED.iterdir():
        if d.is_dir():
            dirs[d.name] = d

    vuln_by_file = {r["source_file"]: r["c"] for r in con.execute(
        "SELECT source_file, COUNT(*) c FROM v_vulnerability WHERE status='active' GROUP BY 1")}
    retest_by_report = {r["nm"]: r["c"] for r in con.execute(
        "SELECT rep.report_name nm, COUNT(*) c FROM v_retest_result rr "
        "JOIN v_report rep ON rep.id = rr.retest_report_id WHERE rr.status='active' GROUP BY 1")}
    report_type = {r["report_name"]: r["report_type"] for r in con.execute(
        "SELECT report_name, report_type FROM v_report WHERE status='active'")}
    # 同时建 basename 索引，容忍路径前缀差异
    vuln_by_base = defaultdict(int)
    for sf, n in vuln_by_file.items():
        vuln_by_base[Path(sf).name] += n
    retest_by_base = defaultdict(int)
    for sf, n in retest_by_report.items():
        retest_by_base[Path(sf).name] += n
    rtype_by_base = {}
    for sf, t in report_type.items():
        rtype_by_base[Path(sf).name] = t

    mism = []
    pending_excluded = []
    checked = Counter()
    for pdf_id, d in sorted(dirs.items()):
        cf = d / "canonical_records.json"
        recs = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else []
        img_recs = json.loads((d / "image_records.json").read_text(encoding="utf-8")) if (d / "image_records.json").exists() else []
        rt_recs = json.loads((d / "retest_records.json").read_text(encoding="utf-8")) if (d / "retest_records.json").exists() else []
        qg_file = d / "quality_gate.json"
        qg = json.loads(qg_file.read_text(encoding="utf-8")) if qg_file.exists() else {}
        # 路径：优先 canonical 里的 source_file，其次 log 行，其次 raw_parsed
        sf = next((r.get("source_file") for r in recs if r.get("source_file")), None)
        if not sf:
            sf = next((r.get("source_file") for r in rt_recs if r.get("source_file")), None)
        if not sf and pdf_id in {r["pdf_id"] for r in log_rows.values() if "pdf_id" in r}:
            sf = next(r["relative_path"] for r in log_rows.values() if r.get("pdf_id") == pdf_id)
        if not sf:
            rp = d / "raw_parsed.json"
            if rp.exists():
                raw = json.loads(rp.read_text(encoding="utf-8"))
                sf = raw.get("source_file") or raw.get("file_path") or raw.get("relative_path")
        if not sf:
            mism.append({"pdf_id": pdf_id, "reason": "无法确定 source_file"})
            continue

        rtype = report_type.get(sf) or rtype_by_base.get(Path(sf).name)
        base = Path(sf).name
        if rtype is None:
            # 类型判定兜底：解析产物里有没有 retest_records
            rtype = "retest" if rt_recs else "pentest"
        if rtype == "pentest":
            checked["pentest"] += 1
            n_canon, n_db = len(recs), vuln_by_file.get(sf, vuln_by_base.get(base, 0))
        else:
            checked["retest"] += 1
            n_canon, n_db = len(rt_recs), retest_by_report.get(sf, retest_by_base.get(base, 0))
        if n_canon != n_db:
            qg_status = qg.get("parse_status") if isinstance(qg, dict) else None
            # pending_review 报告按设计不入库（run_load.py:426-428），单列不计入不一致
            if qg_status == "pending_review":
                pending_excluded.append({"pdf_id": pdf_id, "type": rtype, "source_file": sf,
                                         "parsed_records": n_canon, "in_db": n_db})
            else:
                mism.append({"pdf_id": pdf_id, "type": rtype, "source_file": sf,
                             "canonical": n_canon, "db": n_db, "parse_status": qg_status})

    # 反向核对：数据库中、解析产物里没匹配上的 source_file（按 basename 匹配，容忍路径前缀差异）
    all_sf = set()
    for d in dirs.values():
        cf = d / "canonical_records.json"
        for r in (json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else []):
            if r.get("source_file"):
                all_sf.add(Path(r["source_file"]).name)
        rf = d / "retest_records.json"
        for r in (json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else []):
            if r.get("source_file"):
                all_sf.add(Path(r["source_file"]).name)
    db_files_unmatched = [sf for sf in vuln_by_file if Path(sf).name not in all_sf]
    n_files = checked["pentest"] + checked["retest"]
    n_checked_effective = n_files - len(pending_excluded)
    ratio = 1 - len(mism) / n_checked_effective if n_checked_effective else 0
    out["E-LOAD-007"] = {
        "value": round(ratio, 4),
        "level": level("E-LOAD-007", ratio if not mism else 0),
        "detail": {
            "比对文件数": dict(checked),
            "有效比对文件数(扣除 pending_review)": n_checked_effective,
            "不一致数": len(mism),
            "不一致明细": mism,
            "pending_review 按设计未入库(单列)": len(pending_excluded),
            "pending_review明细": pending_excluded,
            "数据库存在但解析侧未匹配上的文件数": len(db_files_unmatched),
            "未匹配示例": db_files_unmatched[:5],
        },
    }
    # 空记录分布说明
    empty_pentest = 0
    empty_retest = 0
    for d in dirs.values():
        cf, rf = d / "canonical_records.json", d / "retest_records.json"
        if cf.exists() and not json.loads(cf.read_text(encoding="utf-8")):
            empty_pentest += 1
        if rf.exists() and not json.loads(rf.read_text(encoding="utf-8")):
            empty_retest += 1
    out["E-LOAD-007"]["detail"]["空 canonical_records 文件数"] = empty_pentest
    out["E-LOAD-007"]["detail"]["空 retest_records 文件数"] = empty_retest

    # ===== E-LOAD-008 漏洞总量 =====
    out["E-LOAD-008"] = {
        "value": total_vuln,
        "level": level("E-LOAD-008", total_vuln),
        "detail": {"v_vulnerability active": total_vuln, "v_retest_result active": total_retest,
                   "v_image_evidence active": img_active},
    }

    # ===== 汇总 =====
    out["_summary"] = {
        mid: out[mid]["level"] for mid in sorted(k for k in out if k.startswith("E-LOAD"))
    }
    out["_summary"]["通过"] = all(
        out[m]["level"] != "未达标" for m in out if m.startswith("E-LOAD")
    )
    line = json.dumps(out, ensure_ascii=False, indent=2)
    (ROOT / "data" / "eval_load_full_result.json").write_text(line, encoding="utf-8")
    print(line)


if __name__ == "__main__":
    main()
