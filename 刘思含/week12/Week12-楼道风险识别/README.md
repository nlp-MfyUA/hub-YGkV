# 楼道消防安全风险识别

用多模态大模型识别楼道照片中的消防安全隐患，并给出风险等级。

参照 `案例-多模态内容理解.ipynb`：风险标准原文照搬，输出方式从"直接输出类别"改为结构化输出，以便前端展示和统计。

## 风险等级

| 等级 | 枚举值 | 判定 |
| --- | --- | --- |
| 高风险 | `high` | 出现电动车、电瓶、飞线充电等可能起火的元素 |
| 中风险 | `medium` | 大量堆积物严重影响通行，或堆放大量纸箱、木质家具等可燃堵塞物 |
| 低风险 | `low` | 存在堆物现象但不严重 |
| 无风险 | `none` | 楼道干净，无堆放物品 |
| 非楼道 | `non_hallway` | 与楼道无关的图片 |

判定按优先级执行，命中即停：先判是否楼道 → 再看电动元素 → 再看堆物程度。

## 快速开始

```bash
cd /g/ai技能库/课程/Week12-多模态大模型和RAG应用/作业/Week12-楼道风险识别

# 1. 准备配置（只需一次）
cp .env.example .env
#    编辑 .env，填 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY

# 2. 安装依赖（环境里通常已有）
pip install -r requirements.txt

# 3. 先单独验证模型能跑通（强烈建议）
python -X utf8 -m app.test_vl 某张楼道照片.jpg
python -X utf8 -m app.test_vl 某张楼道照片.jpg qwen

# 4. 启动服务
python -X utf8 -m app.main
```

浏览器打开 <http://127.0.0.1:8000>。

## 用手机拍照识别

1. 电脑和手机连**同一个 Wi-Fi**。
2. 查电脑局域网 IP：
   - Windows：`ipconfig`，找"无线局域网适配器 WLAN"下的 IPv4 地址（形如 `192.168.3.40`）
   - 或用本项目脚本：`python -X utf8 -m app.show_ip`
3. 手机浏览器访问 `http://<电脑IP>:8000`，例如 `http://192.168.3.40:8000`。
4. 点"拍照"，手机会直接拉起后置摄像头；也可以从相册选图。
5. 点"开始识别"。

### 打不开时的排查

| 现象 | 原因与处理 |
| --- | --- |
| 手机一直转圈 | 防火墙拦截。以管理员身份运行：`netsh advfirewall firewall add rule name="HallwayRisk8000" dir=in action=allow protocol=TCP localport=8000` |
| 连的是 5G/访客网络 | 手机与电脑要连同一个 SSID；部分路由器开启了"AP 隔离"，需关闭 |
| IP 变了 | 路由器 DHCP 重新分配，重新 `ipconfig` 查一次 |
| 电脑有多个 IP（VMware/VirtualBox 虚拟网卡） | 用 WLAN 那个 `192.168.x.x`，不要用 `192.168.56.1`、`192.168.126.1` |
| 页面能开但拍照按钮无反应 | 用的是 `input capture`，不需要 HTTPS。若你改成 `getUserMedia` 实时取景，则必须 HTTPS |

> 为什么用 `<input type="file" capture="environment">` 而不是 `getUserMedia`：
> `getUserMedia` 在非 HTTPS 的局域网 IP 上被浏览器禁止，而 file input 的 `capture` 属性不受此限制，能直接调用系统相机。代价是没有实时取景框，但对"拍照识别"这个场景足够。

## 接口

```
GET  /                     网页
GET  /api/health           各 provider 的 key 是否配置
POST /api/analyze          上传图片识别
     multipart: file, provider=deepseek|qwen, annotate=true|false
GET  /api/history?limit=20 历史记录
```

`/api/analyze` 返回 `status` 三态：`ok` / `invalid_output`（模型两次输出都不合规）/ `error`，响应体里始终带 `image_url`，前端可以直接展示。

## 目录结构

```
app/
  main.py         FastAPI 入口与路由
  llm.py          Chat[OI] 工厂、provider 切换、颜色/标签映射
  prompt.py       提示词（四条风险定义为作业原文，勿改）
  schemas.py      HallwayRisk / AnalyzeResponse
  analyzer.py     组装多模态消息 → 结构化输出 → 一致性校验 → 重试
  image_utils.py  EXIF 转正、压缩、保存、画标注框
  db.py           SQLite 历史记录
  eval.py         批量评测（混淆矩阵 + 高风险漏判）
  test_vl.py      命令行单图测试
  show_ip.py      打印局域网访问地址
static/
  index.html  app.js  style.css
data/
  uploads/    原始上传图
  annotated/  标注结果图
  eval/       按标签分文件夹的评测集
tests/
  test_core.py    不依赖网络的单元测试
```

## 评测

```bash
# 按 high/medium/low/none/non_hallway 分文件夹放图片
data/eval/high/*.jpg
data/eval/medium/*.jpg

python -X utf8 -m app.eval
python -X utf8 -m app.eval qwen
```

输出准确率、平均耗时、混淆矩阵，并单独列出**高风险漏判**（这是最不能接受的错误类型）。

## 设计要点

- **图片先压缩**：手机原图 3–12MB，base64 后膨胀 33%，容易 413 或超时。前端 canvas 缩到长边 1600，后端再缩到 1280 并转 JPEG q85，实际 payload 约 300KB。
- **EXIF 方向**：手机竖拍的照片方向信息存在 EXIF 里，不处理会横躺，`ImageOps.exif_transpose` 解决。
- **结构化输出**：`with_structured_output(HallwayRisk)` 默认走 ToolStrategy（function calling），跨供应商通用。若某端点不支持，把 `.env` 的 `STRUCTURED_MODE` 改成 `json`。
- **业务校验不交给模型**：判为高风险却没有任何电动元素关键词、分数与等级区间不符、`is_hallway` 与等级矛盾，都会触发一次带纠错提示的重试，两次都失败返回 `invalid_output`。
- **标注框是可选增强**：单独一次调用解析 bbox，失败不影响主结果。

## 已知限制

- 推理耗时 2–6 秒，属于单轮同步调用；没有做流式。
- 评测集需要自己准备，本项目没有内置样例图片。
- AI 结果仅供参考，不能替代消防现场检查。
