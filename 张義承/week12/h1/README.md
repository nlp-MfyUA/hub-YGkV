# 楼道消防安全隐患排查

参考 `案例-多模态内容理解.ipynb` 的思路，构建一个前后端多模态应用：在网页上传楼道照片，后端调用视觉大模型实时判断消防安全隐患等级，并返回隐患点与判断理由。

## 隐患等级

| 等级 | 判定标准 |
|---|---|
| 高风险 | 楼道中出现电动车、电瓶、飞线充电等可能直接起火的元素 |
| 中风险 | 大量堆积物严重影响通行，或堆放大量纸箱、木质家具等可燃物 |
| 低风险 | 存在楼道堆物现象，但数量少、体量小，不严重 |
| 无风险 | 楼道干净整洁，无堆放物品 |
| 非楼道 | 与住宅楼道无关的图片，不参与隐患评级 |

多个隐患同时存在时，按最严重的一项定级。

## 工作流程

```text
浏览器上传图片
   │  POST /api/analyze（multipart）
   ▼
FastAPI 后端
   ├─ 校验格式/大小，Pillow 转正、缩放至 ≤1280px、JPEG 压缩
   ├─ 消防专家提示词 + base64 图片 → DeepSeek Chat Completions
   └─ 解析 JSON、等级归一化 → 返回结构化结果
```

- 模型：`deepseek-v4-flash`（DeepSeek-V4.1-Flash，支持文本 + 图片输入）
- 用户照片只在内存中处理，不写入磁盘
- 纯 HTML/CSS/JS 前端，无需构建

## 快速开始

依赖（当前环境已全部安装）：

```bash
pip install -r requirements.txt
```

配置 API Key（二选一）：

```bash
# 方式一：环境变量
export DEEPSEEK_API_KEY=sk-xxxxxxxx

# 方式二：复制 .env.example 为 .env 并填写
cp .env.example .env
```

启动：

```bash
uvicorn app:app --reload --port 8000
```

浏览器打开 <http://127.0.0.1:8000>，上传照片后点击「开始识别」。

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 无（必填） | 未配置时 `/api/analyze` 返回 503 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容网关地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 需支持图片输入 |
| `MAX_IMAGE_MB` | `10` | 上传图片大小上限 |

## API

### `GET /api/health`

返回服务状态，用于前端提示 Key 是否配置：

```json
{
  "status": "ok",
  "model": "deepseek-v4-flash",
  "key_configured": true,
  "max_image_mb": 10
}
```

### `POST /api/analyze`

`multipart/form-data`，字段名 `file`，支持 JPG / PNG / WebP。

```bash
curl -F "file=@samples/hallway.jpg" http://127.0.0.1:8000/api/analyze
```

成功响应：

```json
{
  "level": "中风险",
  "scene": "楼道",
  "risks": ["大量纸箱、塑料等可燃杂物堆积"],
  "reason": "楼道内堆放大量纸箱等可燃杂物，遇明火易蔓延并阻碍疏散。",
  "elapsed_ms": 4210,
  "model": "deepseek-v4-flash"
}
```

错误响应统一为 `{"detail": "..."}`：

| 状态码 | 场景 |
|---|---|
| 400 | 格式不支持、超过大小限制、图片无法解析 |
| 502 | 上游模型失败、超时、返回格式异常 |
| 503 | 未配置 `DEEPSEEK_API_KEY` |

## 实现说明

- **推理模型的 token 预算**：`deepseek-v4-flash` 会先输出 `reasoning_content`，因此 `max_tokens` 设为 2000，避免结论被截断。
- **提示词与归一化**：提示词要求只输出 JSON；后端仍会剥离代码块、提取 JSON，并把等级统一为五个合法值。模型把非楼道图片标成「无风险」时，后端会强制改为「非楼道」。
- **图片预处理**：EXIF 转正、透明背景铺白、最长边缩放到 1280px、JPEG q85，在保证识别效果的同时降低请求体积和耗时。
- **失败不猜测**：模型返回无法解析时不臆造等级，直接返回 502 让用户重试。

## 目录结构

```text
app.py              FastAPI 入口与路由
analyzer.py         图片预处理、模型调用、结果解析
static/index.html   页面结构
static/styles.css   页面样式与等级配色
static/app.js       上传、请求与结果渲染
requirements.txt    依赖清单
.env.example        配置示例
```

## 与参考案例的关系

参考 notebook 演示了图像分类、YOLO 目标检测、CLIP 打标签、Qwen-VL 图文问答四条路线。本项目采用「视觉大模型 + 结构化输出」路线：无需标注和训练，用一段提示词即可完成带语义解释的风险分级，并能处理「纸箱是否可燃」「画面是否属于楼道」这类需要常识判断的问题；代价是单次推理依赖云端 API，速度与成本受模型服务影响。
