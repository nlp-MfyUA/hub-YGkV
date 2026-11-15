## 本机环境检测 · 2026-11-08
- Python: 3.11.18（路径：E:\Conda\envs\chatbi-vuln\python.exe）
- sqlite3（Python 内置）: 3.53.4，FTS5: 启用
- 操作系统: Windows 10 / AMD64（Windows 11 Pro 10.0.26200）
- CPU 核数: 28（Intel Core i7-14700KF）
- 内存: 31.8 GB
- 磁盘可用: 1399.0 GB（Samsung SSD 990 PRO 2TB）
- GPU: NVIDIA GeForce RTX 5080, 驱动 621.01
- 项目相关全局包版本（仅供对照，不代表将使用）:
  - numpy: 1.26.4（环境内）
  - openai: 1.109.1（环境内）
  - paddleocr: 2.9.1（环境内）

> 说明：检测脚本中 `/proc/meminfo` 为 Linux 专有路径，在 Windows 上不可用；上表内存值由 Windows API（`GlobalMemoryStatusEx`）补充测得。`numpy` / `openai` / `paddleocr` 三项为 2026-11-08 依赖安装完成后在 conda 环境 `chatbi-vuln` 内 `pip show` 查询的结果。

## 环境差异对照
| 项 | 要求 | 本机实际 | 状态 | 处理方式 |
|---|---|---|---|---|
| 操作系统 | Linux / macOS | Windows 11 Pro (10.0.26200) | ⚠️ | 文档最低要求写的是 Linux/macOS；本机为 Windows。路径分隔符问题按 P-DEP-004 处理（统一 `Path.as_posix()`），不阻塞 |
| Python | ≥ 3.11 | 3.11.18 | ✅ | conda 已指定 3.11 |
| SQLite | ≥ 3.34 | 3.53.4 | ✅ | — |
| FTS5 | 启用 | 启用（`(1,)`） | ✅ | — |
| 内存 | ≥ 8 GB | 31.8 GB | ✅ | — |
| 磁盘 | ≥ 5 GB | 1399.0 GB | ✅ | — |
| GPU | 可选 | 有（RTX 5080 / 驱动 621.01） | — | 有：MinerU 可用 GPU；CUDA 与 PyTorch 匹配问题记入报告，Phase 2 再处理 |
| OCR 执行路径 | — | GPU 存在但 OCR 走 CPU | — | 决策：PaddleOCR 使用 CPU 路径。原因：requirements.txt 安装的是 CPU 版 `paddlepaddle`；GPU 加速需改 `paddlepaddle-gpu` 并匹配 CUDA 版本，MVP 不额外引入 GPU 依赖。Phase 2 若 OCR 耗时超标再评估 |
| numpy | 1.26.4（PaddleOCR 要求） | 1.26.4 | ✅ | requirements.txt 锁定，未继承全局 |
| openai | 见 requirements.txt（最终锁定 1.109.1） | 1.109.1 | ✅ | 经用户确认，由 1.54.4 调整为 1.109.1（P-DEP-003） |
| pydantic | 2.9.2 → 2.14.3（经用户确认） | 2.14.3 | ✅ | openai-agents 0.1.0 要求 pydantic>=2.10 |
| paddleocr | 见 requirements.txt（2.9.1） | 2.9.1 | ✅ | 已验证导入 |

### 依赖锁定变更记录（2026-11-08，经用户确认）
- `openai==1.54.4` → `openai==1.109.1`
- `pydantic==2.9.2` → `pydantic==2.14.3`
- 原因：`openai-agents==0.1.0` 要求 `openai>=1.87.0` 且 `pydantic<3,>=2.10`；原锁定组合无法解析。
- 其余依赖版本未改动。
