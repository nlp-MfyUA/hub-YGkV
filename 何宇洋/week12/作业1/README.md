# 廊安：楼道消防风险识别 Demo

参考同目录《案例-多模态内容理解.ipynb》的“多模态图像问答 + 五类风险”方案，将本地 Qwen-VL 推理替换成 DeepSeek 视觉 API。无需 GPU、训练或下载模型权重。原 Notebook 未修改。

## 快速运行（Windows PowerShell）

推荐 Python 3.11+；本项目已在 Python 3.14 环境验证。

```powershell
cd D:\WorkSpace\AILearning\BaDou\workspace\wk12
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

打开 [本地网页](http://127.0.0.1:8000)。也可运行 `./start.ps1`，若脚本被本机执行策略拦截，使用上面的 Python 命令即可。

如果创建虚拟环境时 `ensurepip` 失败，但 `.venv/Scripts/python.exe` 已存在，可由主 Python 的 pip 安装：

```powershell
python -m pip --python .\.venv\Scripts\python.exe install -r requirements-dev.txt
```

默认是模拟演示：选择一张图片后，后端校验图片并返回所选演示类别的**固定示例**，不分析照片内容、不发送外部请求。切换“演示类别”可演示全部五类页面。自动识别可关闭，也可手动点击“开始检测”。

## 人工开启真实识别

按要求，开发和验证阶段跳过了全部真实模型调用和权重下载。真实识别接口已经写好，尚未进行付费联调；实际准确度和延迟需使用真实照片验证。

在**启动后端的同一 PowerShell 窗口**设置：

```powershell
# 如果系统/当前进程已存在 DEEPSEEK_API_KEY，无需再次赋值。
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
$env:DEEPSEEK_MODEL = "deepseek-flash"
$env:ALLOW_PAID_API = "1"
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

重启或重新启动后端并刷新页面，手动选择“真实识别”。此时上传/拍照会产生真实 API 请求；默认“选图后自动识别”已勾选，每次更换图片会发起一次调用。不自动重试。恢复模拟权限可将 `ALLOW_PAID_API` 改为 `0` 后重启。

仅从后端进程环境变量读取 Key；不会发给前端、写进仓库或日志。`.env.example` 只是变量说明，项目**不自动加载 `.env`**。无需在网页填写 Key。

根据核对时的 [DeepSeek 官方接入说明](https://api-docs.deepseek.com/quick_start/agent_integrations/)，V4.1 Flash 使用模型名 `deepseek-flash`。图片通过 [官方视觉接口](https://api-docs.deepseek.com/guides/vision/)的 `image_url` + Base64 传入 `/chat/completions`，JSON 输出、关闭思考模式以减少等待；模型名可用环境变量覆盖。

## 手机拍照

1. 手机和电脑连接同一局域网，执行：

   ```powershell
   .\.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

2. 用 `ipconfig` 查电脑当前网络的 IPv4 地址，在手机浏览器访问 `http://电脑IP:8000`，例如 `http://192.168.1.10:8000`。如访问失败，检查 Wi-Fi 隔离及电脑防火墙是否允许本地网络访问 8000 端口。
3. 点“拍摄照片”，移动端优先使用 `input capture="environment"` 请求系统后置摄像头。具体呈现由浏览器决定，有些浏览器会先显示选择来源。拍完即可上传检测；也可选相册。

电脑浏览器在 `localhost` / `127.0.0.1` 可通过 `getUserMedia` 打开实时相机预览；局域网普通 HTTP 通常不能使用该 API，所以代码会转为系统拍照控件。若需要手机网页内实时预览，请自行准备手机信任的 HTTPS 证书，再启动：

```powershell
.\.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8443 --ssl-certfile cert.pem --ssl-keyfile key.pem
```

这是**拍摄单张后分析**，不连续上传视频。手机实机权限、拍照和 HTTPS 行为需在你自己的设备验证。

## 判断规则

| 类别 | 判断依据 |
| --- | --- |
| 高风险 | 楼道有电动车、电瓶、飞线充电；额外把可见烟火纳入高风险 |
| 中风险 | 大量堆物、严重影响通行，或大量纸箱/木质家具等可燃物 |
| 低风险 | 少量堆物，但不严重 |
| 无风险 | 楼道干净，可见区域无堆放物 |
| 非楼道 | 图片不是楼道、走廊或楼梯间 |

先检查图像可判读性与场景，再按高 → 中 → 低 → 无风险顺序取最高风险。非楼道不因出现电动车而被判为楼道高风险。图片模糊/过暗或场景不确定返回“待复核”（`risk: null`），这是分析状态，不是新增风险类别。模型提取可见事实，后端统一执行分级规则；不输出未经校准的置信度。

结果包括类别、场景描述、可见证据、处理建议、不确定项及耗时，可下载 JSON。当前页面最多保留 20 条巡检记录，刷新即清空，不保存照片和报告到服务端。模型输出只作为文本渲染。

## 项目结构与接口

```text
backend/main.py       FastAPI 路由、前端托管、演示/真实调用开关
backend/service.py    图片校验、EXIF 处理、DeepSeek 图片请求、异常处理
backend/risk.py       结构化观察、分级规则与固定演示数据
frontend/index.html   单页界面
frontend/style.css    手机/电脑响应式样式
frontend/app.js       相机、上传、异步分析、报告、临时记录
tests/test_app.py     无付费调用的接口及分级测试
start.ps1             可选启动脚本
```

- `GET /api/config`：返回开关和 Key 是否存在，不返回 Key 本身。
- `POST /api/analyze`：`multipart/form-data`，`file` 为图片、`mode=demo|live`、`preset=high|medium|low|none|not_corridor`（只影响 demo）。
- [自动生成的接口文档](http://127.0.0.1:8000/docs)。

图片限制 10 MB，按实际内容校验 JPEG/PNG/WebP/GIF，GIF 只分析首帧；不支持 HEIC，请转 JPEG。拒绝过大像素图片，矫正 EXIF 方向，去掉 EXIF 信息，并将长边缩至不超过 1600px 后发送。无数据库、账号和 GPU 依赖；这是用于本机/可信局域网的课程 Demo，若对外部署应另外添加鉴权与请求限流。

## 验证

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
node --check frontend/app.js
```

测试用生成图片与模拟的 HTTP 响应验证五类规则、优先级、模糊照片、非法图片、付费开关、API 请求结构、超时与异常响应；不调用真实 DeepSeek、不下载模型。人工验收建议：模拟五类 → 手机拍照/相册 → 人工开启真实接口后，用真实楼道照片检查效果。

本次验证：32 项后端测试通过，前端 JavaScript 语法检查通过。使用本机 Chrome 和模拟摄像头验证了图片上传、五类结果切换、拍照采集、报告下载、记录清空，以及 390px 手机尺寸下无横向溢出；浏览器无 JavaScript 错误。截图见 [桌面版](artifacts/demo-desktop.png)、[手机版](artifacts/demo-mobile.png)。截图中的图片为程序绘制的测试图，不是模型识别素材。

可选浏览器验收脚本 `tests/browser-smoke.cjs` 需要本机已有 Playwright 和 Chrome，并且先启动本地服务；脚本本身不会安装或下载浏览器。运行方式：`node tests/browser-smoke.cjs <本机已安装的playwright模块路径>`。真实 DeepSeek 图片推理效果及手机实机拍照未验证。
