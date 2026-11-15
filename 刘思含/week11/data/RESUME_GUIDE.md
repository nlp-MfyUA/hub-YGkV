# 全量入库恢复手册

## 插上硬盘后的第一步

1. 确认 `deliverables/` 下 363 份 PDF 可读；
2. 确认 `data/parsed_output/` 下约 90 个带 `quality_gate.json` 的目录存在；
3. 读 `data/PROGRESS_SNAPSHOT.md` 了解当前状态。

## 检查是否有残留进程

```bash
tasklist | findstr /I python
```

如果有 `run_full_batch.py` 在运行，先等待其结束或确认后再继续。

## 恢复批次 1 的剩余 140 份

```bash
python -m pipeline.run_full_batch \
    --batch data/full_batch.json \
    --batch-index 1 \
    --db-path app/db/vuln.db \
    --progress-every 10
```

说明：

- 脚本没有 `--resume-from` 参数。它会遍历批次 1 的全部 200 份，对已有 `quality_gate.json` 的报告直接复用（**不重新解析、不重跑 OCR**），只解析缺失的；
- 已在 `v_report` / `pdf_index` 中的报告不会重复加载；
- 因此直接重跑即可，等价于“从断点恢复”。

## 批次 1 完成后

执行 `PROGRESS_SNAPSHOT.md` 中对应的 6 条验证 SQL（报告数 / 漏洞数 / 类型分布与 UNKNOWN 占比 / severity 分布 / FTS 一致性 / parse_status 计数），并按任务要求判断：

- `v_vulnerability` ≥ 1200（口径见 `docs/04_evaluation.md` E-LOAD-008：按 157 份有漏洞的渗透报告 × 平均 7.9 条估算，不按 363 份全量估算）；
- `unknown_rate` ≤ 30%；
- `pending_review` ≤ 30 份；
- FTS 一致。

全部通过后再进入批次 2。

## 批次 2

```bash
python -m pipeline.run_full_batch \
    --batch data/full_batch.json \
    --batch-index 2 \
    --db-path app/db/vuln.db \
    --progress-every 10
```

完成后执行 8 条 SQL（含 retest 匹配情况与 `vuln_id IS NULL` 统计）与 E-LOAD 指标验证（见 `docs/04_evaluation.md` §3）。

## 如果内存再次不足

1. 把批次 1 拆成更小的批次（例如每批 30–50 份），可临时在 `data/full_batch.json` 之外生成小批次文件；
2. 或在 `run_full_batch.py` 的解析循环中，每处理 10 份显式 `gc.collect()`；
3. 注意：`PaddleOCR` 的 `use_angle_cls` 当前解析路径中并未传参（使用库默认值），若要调整需先核对 `pipeline/phase2_parse/image_extractor.py`，并评估对 OCR 准确率的影响。
