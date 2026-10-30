# 楼道消防隐患智能识别

基于 **YOLOv8 本地物体检测 + DeepSeek 多模态研判** 的楼道消防安全巡检应用。网页可直接调用手机摄像头拍照或上传现场图片：

1. **YOLO 先检测**：在浏览器本地运行 YOLOv8n，实时在画面上绘制检测框，并展示识别到的物体；
2. **DeepSeek 再研判**：后端把图片和 YOLO 检测摘要一起交给 DeepSeek Flash，输出风险等级、隐患依据与处置建议。

API Key 只保存在服务端，不会暴露给浏览器。

## 功能

- **YOLO 实时检测**：摄像头画面约每秒进行一次本地推理，实时显示人、自行车/摩托车、椅子、背包等物体检测框；拍照或上传图片后也会自动检测并展示物体列表。
- **手机拍照**：实时调用手机后置摄像头，支持前后摄像头切换；非 HTTPS 环境可降级调用系统相机。
- **图片上传**：支持点击选择、拖拽上传，自动压缩图片后再发送。
- **五级风险研判**：无隐患、低风险、中风险、高风险、非楼道。
- **按风险着色**：结果卡片、风险徽章、识别记录相框均按风险等级使用对应颜色。
- **隐患明细**：输出通道占用、可燃物、电动车/充电行为等判断，以及画面依据和处置建议。
- **识别记录**：识别完成的照片以相框形式保存在页面下方，按风险着色，点击可查看完整结果；最多保留 12 条。
- **中文界面**：全站中文，移动端优先布局。

## 识别流程

```
手机摄像头 / 图片上传
          │
          ▼
┌───────────────────────┐
│ YOLOv8n（浏览器本地）  │  onnxruntime-web + wasm
│ 实时画框 / 物体列表     │
└──────────┬────────────┘
           │ 图片 + 检测摘要
           ▼
┌───────────────────────┐
│ DeepSeek Flash（后端） │  多模态视觉研判
│ 风险等级 / 依据 / 建议  │
└──────────┬────────────┘
           ▼
   风险着色结果 + 识别记录
```

> YOLO 只负责定位通用物体（COCO 80 类），无法直接识别纸箱、电瓶、飞线等类别；电动车可能被识别为摩托车或自行车。最终风险等级由 DeepSeek 结合画面内容判定。

## 风险分级标准

| 等级 | 判定标准 |
| --- | --- |
| **高风险** | 楼道中出现电动车、电瓶、飞线充电等可能起火的元素；或存在明火、烟雾、燃气罐等。 |
| **中风险** | 楼道中存在大量堆积物严重影响通行，或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物。 |
| **低风险** | 存在楼道堆物现象，但不严重，基本不影响通行。 |
| **无隐患** | 楼道干净整洁，无堆放物品，通道畅通。 |
| **非楼道** | 与居民楼楼道无关的图片，不参与楼道隐患判定。 |

判定时取最高风险等级：只要出现电动车或飞线充电，即判定为高风险。

## 快速开始

要求 Node.js 18 及以上版本（后端使用内置 `fetch`）。

```bash
# 1. 安装依赖
npm install

# 2. 配置环境变量
cp .env.example .env

# 3. 编辑 .env，填写 DeepSeek API Key
#    DEEPSEEK_API_KEY=sk-xxxx
```

然后启动（一条命令同时起前端和接口）：

```bash
npm run dev      # 前端 3000 + 接口 3001
```

打开 `http://localhost:3000` 即可使用。首次打开页面会加载 YOLOv8 模型（约 12MB），加载完成后摄像头画面会开始实时检测。

需要单独启动某个进程时：

```bash
npm run server   # 只启动后端接口，3001
npm run start    # 只启动前端开发服务器，3000（被占用会自动顺延端口）
npm run start:lan # 前端监听 0.0.0.0，供手机通过局域网访问
```

### 端口约定（出问题先看这里）

- **3001 必须是后端接口**。页面提示「无法连接识别服务」时，先确认 `npm run server` 在跑。
- 3000 被占用时 CRA 会自动顺延端口。如果它顺延到了 **3001**，`/api` 请求会被代理回自己，接口返回 431，页面就会提示无法获取配置。现在这种情况会直接返回明确的 503 提示，按提示换端口（如 `PORT=3002 npm start`）即可。
- 检查端口占用：`lsof -nP -iTCP:3000 -iTCP:3001 -sTCP:LISTEN`。

## 手机访问与摄像头权限

浏览器只在 **HTTPS 或 localhost** 下允许网页调用实时摄像头。手机通过局域网 IP 访问属于非安全上下文，`getUserMedia` 会被浏览器禁用，页面会自动降级为「调用系统相机」拍照（调起手机原生相机，拍完直接上传识别）。

局域网访问（前端要监听 `0.0.0.0`，所以用两个终端）：

```bash
npm run server      # 终端 1：接口 3001
npm run start:lan   # 终端 2：前端 0.0.0.0:3000
# 手机打开 http://<电脑局域网 IP>:3000
```

如果需要在手机上使用**网页内实时摄像头 + YOLO 实时检测**，用内网穿透工具拿一个 HTTPS 域名即可：

```bash
npx localtunnel --port 3000
# 或
cloudflared tunnel --url http://localhost:3000
```

手机打开隧道给出的 `https://...` 地址后，实时拍照、切换摄像头和 YOLO 实时检测都可正常使用。

## 生产构建

```bash
npm run build   # 生成 build/ 静态文件
npm run serve   # 构建并由 Express 在 3001 端口同时提供页面与 API
```

生产环境下 Express 会自动托管 `build/`，所有 `/api/*` 请求由后端处理，其余路径回退到 `index.html`。

## 本地 YOLO 模型

- `public/model/yolov8n.onnx`：YOLOv8n 目标检测模型（COCO 80 类，约 12MB）
- `public/model/nms-yolov8.onnx`：NMS 后处理模型
- 推理完全在浏览器中通过 `onnxruntime-web` 的 wasm 后端完成，不上传视频帧
- 模型输入 640×640，前端使用 Canvas 做等比 letterbox 预处理并还原检测框坐标
- 可通过替换 `public/model/yolov8n.onnx` 使用自训练模型，同时更新 `src/utils/labels.json` 与 `src/utils/labelZh.js`

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `SERVER_PORT` | 后端端口 | `3001` |
| `SERVER_HOST` | 后端监听地址 | `0.0.0.0` |
| `MAX_IMAGE_MB` | 单张图片大小上限 | `10` |
| `REQUEST_TIMEOUT_MS` | 模型调用超时 | `90000` |
| `RATE_LIMIT_PER_MINUTE` | 单 IP 每分钟识别次数 | `30` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 空 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | DeepSeek 多模态模型名 | `deepseek-flash` |

> 实际可用的模型 ID 以 DeepSeek 控制台为准，可通过 `DEEPSEEK_MODEL` 覆盖。

## 接口

### `GET /api/config`

返回服务配置（不包含任何 Key）：

```json
{
  "defaultProvider": "deepseek",
  "maxImageMB": 10,
  "providers": [
    {
      "id": "deepseek",
      "name": "DeepSeek Flash",
      "description": "深度求索多模态模型",
      "model": "deepseek-flash",
      "available": true
    }
  ]
}
```

### `POST /api/analyze`

`multipart/form-data`：

- `image`：图片文件，必填
- `detections`：可选，前端 YOLO 检测摘要的 JSON 字符串

`detections` 示例：

```json
[
  { "label": "motorcycle", "labelZh": "摩托车/电动车", "count": 1, "maxScore": 0.87 },
  { "label": "chair", "labelZh": "椅子", "count": 2, "maxScore": 0.62 }
]
```

响应示例：

```json
{
  "provider": "deepseek",
  "provider_name": "DeepSeek Flash",
  "model": "deepseek-flash",
  "elapsed_ms": 3210,
  "analyzed_at": "2026-10-30T12:00:00.000Z",
  "yolo_detections": [
    { "label": "motorcycle", "labelZh": "摩托车/电动车", "count": 1, "maxScore": 0.87 }
  ],
  "result": {
    "scene_type": "楼道",
    "is_hallway": true,
    "risk_level": "high",
    "risk_label": "高风险",
    "confidence": 0.93,
    "summary": "楼道内停放电动车并从室内拉线充电，存在起火风险。",
    "passage_blocked": true,
    "combustibles_present": true,
    "charging_detected": true,
    "hazards": [
      {
        "title": "电动车楼道停放",
        "severity": "high",
        "description": "画面右侧停放一辆电动车，占据楼道主要通道。"
      }
    ],
    "evidence": ["电动车停放在楼梯口附近", "可见从室内引出的插排电线"],
    "suggestions": ["立即拔除充电线并将电动车移出楼道", "联系物业或社区网格员到场处置"]
  }
}
```

## 项目结构

```
.
├── public/
│   ├── model/               # yolov8n.onnx + nms-yolov8.onnx
│   ├── favicon.svg
│   ├── index.html
│   └── manifest.json
├── server/
│   ├── index.js             # Express 入口、上传、限流、静态托管
│   ├── config.js            # 环境变量与 DeepSeek 配置
│   ├── prompt.js            # 消防隐患研判提示词
│   ├── vision.js            # DeepSeek 多模态调用
│   ├── normalize.js         # JSON 解析、结果规范化、YOLO 摘要校验
│   └── errors.js
├── src/
│   ├── App.js               # 页面状态、识别流程、历史记录
│   ├── api.js               # 后端接口封装
│   ├── constants.js         # 风险等级与颜色
│   ├── hooks/
│   │   └── useYolo.js       # YOLO 模型加载状态
│   ├── components/
│   │   ├── CapturePanel.js  # 拍照、上传、实时检测、画框
│   │   ├── ResultPanel.js   # 风险结果展示
│   │   ├── HistoryPanel.js  # 相框式识别记录与详情弹窗
│   │   ├── RiskGuide.js     # 分级标准
│   │   └── icons.js
│   ├── utils/
│   │   ├── yolo.js          # YOLOv8 预处理、推理、NMS、画框
│   │   ├── labelZh.js       # COCO 中文标签
│   │   ├── labels.json      # COCO 英文标签
│   │   ├── download.js      # 模型下载进度
│   │   ├── image.js         # 拍照截帧、图片压缩、缩略图
│   │   └── history.js       # localStorage 历史记录
│   └── style/
├── .env.example
├── craco.config.js          # 复制 onnxruntime wasm
└── package.json
```

## 说明

- 视频帧只在浏览器本地做 YOLO 推理，不会上传；点击识别后，仅当前照片会发送给 DeepSeek 做多模态研判。
- 服务端不落盘保存照片；识别记录只保存在浏览器 `localStorage` 中，最多 12 条，可一键清空。
- 上传图片会先在前端压缩（最长边 1600px），减少流量与模型调用耗时。
- 识别结果由大模型生成，仅供参考，不能替代专业消防检查；紧急火情请立即拨打 119。
- 每个 IP 默认每分钟最多 30 次识别请求，可在 `.env` 中调整。
- YOLOv8 模型来自 [Ultralytics](https://github.com/ultralytics/ultralytics)，遵循其开源许可。
