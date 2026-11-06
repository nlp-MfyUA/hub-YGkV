# 楼道消防安全多模态识别 Demo

手机拍照 → 视觉大模型识别 → 五级风险判定的端到端原型。后端 FastAPI，前端移动端 Web（原生 JS），
评测子系统离线可复现。

```
┌─────────────────── 前端（移动端 Web，原生 JS）───────────────────┐
│ getUserMedia 预览 → canvas 拍照（长边 1600 / JPEG 0.85）→ 上传   │
│ 结果渲染：等级色块 / 置信度 / evidence / signals / 法规提示       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ multipart/form-data
┌──────────────────────────▼──────────────────────────────────────┐
│               后端（FastAPI + Uvicorn，backend/）                 │
│  POST /api/analyze                                               │
│   ├─ 校验（MIME / 大小 ≤8MB / 短边 ≥224px）                      │
│   ├─ Base64 编码                                                 │
│   ├─ Prompt 构造（场景分类 + 五级判据 + 冲突规则）                │
│   ├─ VisionProvider（deepseek 主通道 / qwen 备选，可重试）        │
│   ├─ JSON 容错解析 + Pydantic 枚举校验                           │
│   ├─ 服务端二次裁决（多信号取最高，arbiter_override 标记）        │
│   └─ 结构化响应 + 元数据日志（不记图片内容）                      │
│  GET /api/health  GET /api/config   静态托管 frontend/           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ OpenAI 兼容协议
            视觉大模型 API：deepseek-v4.1-flash（主）/ qwen-vl-max（备）

┌─────────────────── 评测子系统（离线，eval/）─────────────────────┐
│ dataset/labels.csv → run_eval.py → 混淆矩阵 / P-R-F1 / report.md │
└─────────────────────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 1. 安装依赖（Python 3.11+）
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env    # 然后填写 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL

# 3. 验证主通道连通性（建议每次改配置后先跑这个）
python scripts/check_provider.py --provider deepseek

# 4. 启动服务
uvicorn backend.main:app --host 0.0.0.0 --port 8000
# 浏览器访问 http://localhost:8000
```

`getUserMedia` 要求安全上下文：`localhost` 可直接用；**手机真机**必须走 HTTPS 隧道：

```bash
cloudflared tunnel --url http://localhost:8000   # 或 ngrok http 8000
# 用生成的 https:// 地址在手机浏览器打开
```

## 目录结构

```
├── backend/
│   ├── main.py            # FastAPI 应用：/api/* + 静态托管 + 错误矩阵 + 日志
│   ├── config.py          # .env 读取（pydantic-settings）
│   ├── schemas.py         # 五级枚举 / Signal / ModelOutput / 响应模型
│   ├── prompt.py          # 系统提示词（八区块）+ 法规提示文案
│   ├── arbiter.py         # 服务端二次裁决：多信号取最高
│   ├── utils.py           # 图片校验 / Base64 / JSON 容错解析
│   ├── errors.py          # 错误码 → HTTP 状态映射
│   └── providers/         # base（抽象+共享）/ deepseek / qwen / 工厂
├── frontend/              # index.html / app.js / style.css（无第三方依赖）
├── eval/
│   ├── run_eval.py        # 批量评测 CLI
│   ├── metrics.py         # 混淆矩阵 / P-R-F1 / 延迟分位
│   └── dataset/           # labels.csv + 五类图片目录
├── scripts/
│   └── check_provider.py  # 启动前连通性自检
├── .env.example
└── requirements.txt
```

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/analyze` | `multipart/form-data`，字段 `image`；返回五级判定 + signals + 裁决标记 |
| GET | `/api/health` | 服务与通道配置状态（不含密钥） |
| GET | `/api/config` | 脱敏配置：provider / model / 大小上限 / 超时 |

成功响应示例：

```json
{
  "request_id": "a1b2c3d4",
  "risk_level": "高风险",
  "confidence": "high",
  "evidence": "画面右侧楼梯口停放一辆两轮电动车，车旁有充电线延伸至门缝。",
  "scene_type": "stairwell",
  "signals": [
    {"type": "电动车", "level": "高风险", "detail": "右侧楼梯口两轮电动车"},
    {"type": "飞线充电", "level": "高风险", "detail": "门缝延伸出充电线"}
  ],
  "arbiter_override": false,
  "provider": "deepseek",
  "model": "deepseek-v4.1-flash",
  "latency_ms": 2345
}
```

错误响应统一为 `{"request_id", "error_code", "detail"}`，错误码矩阵：

| error_code | HTTP | 前端提示 |
|---|---|---|
| `unsupported_image_type` | 422 | 请上传 JPEG/PNG/WebP |
| `image_too_large` | 413 | 图片过大，请重拍 |
| `image_too_small` | 422 | 图片过小，请重拍 |
| `model_timeout` | 504 | 识别超时，请重试 |
| `model_upstream_error` | 502 | 识别服务异常，请稍后重试 |
| `model_output_unparseable` | 502 | 识别结果异常，请重试 |
| `invalid_enum` | 502 | 识别结果异常，请重试 |
| `provider_not_configured` | 503 | 服务未配置 |
| `unauthorized` | 401 | 演示令牌校验失败（设置 `DEMO_TOKEN` 后启用） |

## 评测

```bash
# 1. 准备数据集：每类 ≥15 张放入 eval/dataset/<等级>/，
#    并在 eval/dataset/labels.csv 登记（filename,true_label）
#    命名建议：{high|mid|low|none|na}_{序号}.jpg
# 2. 跑基线
python eval/run_eval.py --dataset eval/dataset --provider qwen --out eval/report.md
# 常用参数：--limit 20 抽样 ｜ --concurrency 2 并发（默认 1 防限流）
# 3. 报告含：总体准确率、5×5 混淆矩阵、各类 P/R/F1、
#    高风险召回率（单独突出）、错误样本清单、平均/P95 延迟、解析失败率
```

调优方法：看报告里混淆最多的类别对（如「纸箱 vs 泡沫箱」「车库电动车」），
在 `backend/prompt.py` 对应规则块补反例描述，再跑一轮对比。

## 配置说明（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `VISION_PROVIDER` | `deepseek` | 主通道；跑不通一键切 `qwen` |
| `DEEPSEEK_API_KEY` / `_BASE_URL` / `_MODEL` | 空 / `deepseek-v4.1-flash` | 按服务商文档填写 |
| `QWEN_API_KEY` / `_BASE_URL` / `_MODEL` | DashScope compatible-mode / `qwen-vl-max` | 备选通道 |
| `MAX_IMAGE_MB` / `MIN_IMAGE_SIDE` | 8 / 224 | 图片大小与短边下限 |
| `TIMEOUT_S` / `MAX_RETRIES` | 30 / 1 | 超时与重试（仅网络错误与 5xx 重试） |
| `DEMO_TOKEN` | 空 | 设置后 `/api/analyze` 需带 `X-Demo-Token` 头 |

> **实测备注**：在 `https://api.deepseek.com` 上，设计文档默认的 `deepseek-v4.1-flash`
> 并非可用模型名（返回 HTTP 400，自检脚本会给出诊断）；实际可用为 `deepseek-flash`
> 与 `deepseek-v4-pro`。本地 `.env` 已按 `deepseek-flash` 配置并验证通过，
> 这正是 `check_provider.py` 要解决的问题——换服务商/换模型后先跑自检再启动。

## 设计要点

- **两段式判定 + 双保险**：模型先定场景再列信号，服务端裁决器按权重表重算等级，
  与模型自报不一致时以服务端为准并标记 `arbiter_override`。
- **白名单显式化**：灭火器箱、消火栓等消防器材明确"不计入堆物"，降低误判。
- **车库电动车例外**：`garage_passage` 内停放不判高风险，但飞线充电 / 堵塞通道照常判。
- **图片不落盘**：上传字节仅在内存中处理，日志只记元数据。
- **Key 只在后端**：`.env` 已加入 `.gitignore`，前端只调同源 `/api/*`。

## 明确不做

用户体系 / 数据库 / 历史持久化 / 视频流 / 模型微调 / 生产级并发与限流 / 语音 / 多语言。
