## 参照机 · 2026-11-08
- CPU: Intel Core i7-14700KF / 28 逻辑核
- 内存: 31.8 GB
- 磁盘: Samsung SSD 990 PRO 2TB（可用 1399.0 GB）
- 操作系统: Windows 11 Pro (10.0.26200) / AMD64
- Python: 3.11.18（conda 环境 chatbi-vuln）
- SQLite: 3.53.4（FTS5 启用）
- OCR: PaddleOCR 2.9.1（CPU；已验证导入）
- GPU: NVIDIA GeForce RTX 5080（驱动 621.01）
- 是否启用 MinerU: 否（当前使用 pdfplumber；MinerU 为 Phase 2 可选）

## Phase 2 OCR 耗时基线 · 2026-11-08
- 样本：3 份真实报告（slot 3 渗透 54 页 63 图、slot 6 回归 33 页 45 图、无漏洞 9 页 1 图）
- 单图均摊：2.55s / 3.24s / 5.7s
- 全量估算：363 份 × 平均 20 张有效图 ≈ 7,000–10,000 张，总耗时约 5–8 小时
- 结论：CPU OCR 在 MVP 阶段可接受，不触发 09_fallback_plan.md F-02 的 GPU 评估（阈值 24 小时）
