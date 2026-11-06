# 作业1 · 楼道消防风险识别（前后端多模态应用）

参考课程案例 `02-多模态大模型/案例-多模态内容理解.ipynb`，构建一个带前后端的多模态应用：
网页端调用手机摄像头拍照 / 上传图片，后端调用 **DeepSeek V4.1 Flash**（图像理解能力）实时判定
楼道场景的消防隐患等级。

## 1. 功能

### 前端（单页，手机优先，零构建工具）
- **📷 开启摄像头**：调用 `getUserMedia`，手机默认调后置摄像头（`facingMode: environment`）
- **⏺ 拍摄并识别**：canvas 截取视频帧 → 客户端压缩（最长边 1280px / JPEG 0.85）→ 提交识别
- **🖼 上传图片识别**：文件选择 + 桌面端拖拽，两条路径共用同一提交链路
- **结果卡片**：按等级分色（高风险红 / 中风险橙 / 低风险黄 / 无风险绿 / 非楼道灰），
  展示等级、判定理由、识别到的风险元素、耗时与 token
- **历史记录**：最近 20 条存 localStorage，带缩略图

### 后端（FastAPI）
- `GET  /api/health` → 模型名、网关地址、Key 配置状态
- `POST /api/recognize` → 接收 `{"image": "data:image/jpeg;base64,..."}`，
  调 DeepSeek 图像理解接口，返回 `{category, elements, reason, model, prompt_tokens, completion_tokens, elapsed_ms, request_id}`
- 分类结果强制校验，只接受五档之一；模型输出解析失败 / 类别越界 / 网关异常均返回明确错误信息
- 同时监听 **HTTP 8000** 与 **HTTPS 8443**（首次运行自动生成自签名证书）

## 2. 风险分类标准（沿用课程案例提示词）

| 类别 | 判定标准 |
|------|----------|
| 高风险 | 楼道中出现电动车、电瓶、飞线充电等可能起火的元素 |
| 中风险 | 大量堆积物严重影响通行，或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物 |
| 低风险 | 存在楼道堆物现象但不严重 |
| 无风险 | 楼道干净，无堆放物品 |
| 非楼道 | 与楼道场景无关的图片 |

## 3. 启动

```powershell
cd 作业1-楼道风险识别
python app.py            # HTTP :8000 + HTTPS :8443
```

也提供两个一键脚本（任选其一）：

| 脚本 | 用法 | 说明 |
|------|------|------|
| `启动.cmd` | 双击 | 推荐，不受 PowerShell 执行策略限制 |
| `run.ps1` | `.\run.ps1` | 若提示「未对文件进行数字签名」，用：`powershell -ExecutionPolicy Bypass -File .\run.ps1` |

> `run.ps1` 已存为 UTF-8 with BOM，否则 Windows PowerShell 5.1 按 GBK 读取中文注释会报语法错误。

依赖（本机 Python 3.14 已预装全部所需包）：`fastapi`、`uvicorn`、`python-dotenv`、
`cryptography`、`python-multipart`。**模型调用使用标准库 `urllib` 直调 OpenAI 兼容接口，
不需要 openai SDK**。

配置在项目根目录 `.env`（已在 `.gitignore` 中排除）：

```
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=http://192.168.124.88:7863/v1
DEEPSEEK_MODEL=cn:deepseek-v4.1-flash
```

## 4. 访问方式

| 端 | 地址 | 说明 |
|----|------|------|
| 本机 | `http://localhost:8000` | localhost 属安全上下文，**摄像头可用** |
| 手机（上传） | `http://<局域网IP>:8000` | HTTP 下摄像头被浏览器禁用，仅能上传 |
| 手机（拍照） | `https://<局域网IP>:8443` | 自签名证书，提示不安全时点「高级 → 继续前往」 |

> 浏览器 `getUserMedia` 仅在 HTTPS 或 localhost 下可用，这是浏览器的硬性安全策略。
> 手机上要用摄像头，必须走 HTTPS 端口。

## 5. 模型调用要点（实测确认）

- 接口：`POST {BASE_URL}/chat/completions`，OpenAI 兼容格式，图片以 base64 data URL 内联
  （`data:image/jpeg;base64,...`），放在 **user** 消息的 content 块数组里
- 支持格式：JPEG / PNG / GIF / WebP
- 结构化输出：`response_format: {"type": "json_object"}`，提示词中需包含 "json" 字样
- **`max_tokens` 必须留足（当前 2000）**：该模型带思维链，token 过小会导致最终 `content` 为空、
  `finish_reason=length`，此时后端会返回明确错误而非静默失败
- 网关模型名 `cn:deepseek-v4.1-flash`，响应中 `model` 字段回显 `deepseek-v4.1-flash`

## 6. 实测验证

后端接口 + 前端全链路均已实测通过（CDP 驱动真实 Chrome 注入文件触发真实上传流程，
并用 Chrome 假摄像头跑通拍照流程）。

| 测试图 | 场景 | 判定 |
|--------|------|------|
| `corridor_clutter_high_boxes.jpg` | 楼道口大量纸箱、木质家具堆积 | 中风险 ✅ |
| `corridor_door_clutter.jpg` | 单元门外堆放置物架、塑料筐 | 低风险（偶有漂移） |
| `corridor_scooter_chair.jpg` | 楼道内滑板车、椅子、购物袋 | 低风险 ✅ |
| `stairwell_bicycle.jpg` | 楼梯间停放自行车 | 低风险 ✅ |
| `non_corridor_pingpong.jpg` | 室内乒乓球活动 | 非楼道 ✅ |
| 其余 8 张 | 文字图 / 全黑图 / 室外电动车 | 非楼道 ✅ |

单次识别耗时 2.2–32 s（受思维链长度影响），prompt_tokens 约 460–1280。

**完整测试报告、稳定性分布、已知缺口**见 [`tests/RESULTS.md`](tests/RESULTS.md)。

### 复现测试

```powershell
python tests\test_api.py          # 全样本分类回归 -> tests/results.json
python tests\test_e2e.py           # 前端上传 + 拍照两条链路 -> tests/e2e_result.json
python tests\measure_stability.py 8   # 重复 8 次统计判定分布
```

## 7. 目录结构

```
作业1-楼道风险识别/
├── app.py              # FastAPI 后端（含模型调用、JSON 解析、HTTPS 证书生成、思维链超预算重试）
├── static/
│   ├── index.html      # 前端单页（拍照 / 上传 / 结果 / 历史）
│   └── favicon.svg
├── tests/
│   ├── test_api.py         # 后端接口与分类回归
│   ├── test_e2e.py         # 前端端到端（CDP 驱动 Chrome）
│   ├── measure_stability.py# 判定稳定性统计
│   ├── make_synthetic.py   # 合成验证图生成
│   ├── samples/            # 14 张测试样本图
│   ├── RESULTS.md          # 测试报告（实测数据、稳定性、已知缺口）
│   ├── SAMPLES.md          # 样本图来源与授权
│   └── results.json / e2e_result.json / stability.json   # 实测原始输出
├── requirements.txt
├── run.ps1             # Windows 一键启动（UTF-8 BOM）
├── 启动.cmd             # 双击启动，不受执行策略限制
├── .env                # API Key 与网关配置（git 忽略）
├── .gitignore
├── certs/              # 自动生成的自签名证书（git 忽略）
└── README.md
```
