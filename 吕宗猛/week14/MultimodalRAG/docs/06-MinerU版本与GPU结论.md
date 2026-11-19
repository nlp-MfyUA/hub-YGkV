# MinerU 版本与 GPU 结论

## 1. 版本核对（2026-11-12）

| 来源 | 结果 |
|---|---|
| GitHub Releases | 最新稳定版 `4.2.1`（2026-11-11 发布），上一版 `4.2.0`（2026-11-10） |
| GitHub Tags | 无 `5.x` 标签 |
| PyPI 安装约束 | `mineru>=4.0,<5` |

> `MinerU2.5` 是 **模型版本名**（`MinerU2.5-2509-1.2B`，2025-09 发布），不是软件包 5.x。它被 `standard` 档的 VLM 使用。

## 2. 档位与 GPU

| 档位 | 主要用途 | 本地执行 | 是否需要 GPU |
|---|---|---|---|
| `flash` | 原生 PDF 文本 / Office / 快速预览 | 原生文本解析 + Flash OCR | 否 |
| `basic` | 基础 OCR、公式、表格 | ONNX/Torch 小模型 | 否 |
| `standard` | 复杂版面、高质量解析 | 小模型 + MinerU2.5 VLM | 建议 GPU |
| `advanced` | 更高质量 | 复用 standard 模型，更多推理 | 建议 GPU |

## 3. 飞牛结论

- 飞牛 `nvidia-smi` 不存在，无 NVIDIA GPU。
- 6 核 CPU 按 MinerU 自动档位规则属于 4–11 核区间，只自动开放到 `basic`。
- 因此本项目固定 `MINERU_TIER=basic`，使用 CPU ONNX 小模型，不占用 GPU。
- 若后续出现大量截图/扫描件且识别率不足，可把 `MINERU_URL` 指向一台带 3090/AutoDL 的 MinerU `standard` 服务，仅改环境变量即可。
