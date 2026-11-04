# 楼道消防安全隐患智能识别系统

> 课程作业完整项目：手机网页拍照 / 图片上传 + Python FastAPI + DeepSeek V4.1 Flash / Qwen3-VL-Flash + 消防风险五级判定

## 一、功能

- 手机或电脑网页上传 JPG、PNG、WebP 图片
- 网页实时摄像头取景并拍照；手机另提供系统拍照入口
- 选择 DeepSeek V4.1 Flash 或 Qwen3-VL-Flash 分析图片
- AI **只判断画面中的物品和场景**，Python 代码按标准固定计算风险等级
- 输出五类结果：**非楼道、高风险、中等风险、低风险、无隐患**
- 输出现场描述、可见证据、整改建议
- 可查看明确标注的静态示意报告（不是 AI 真实识别）

## 二、Windows 快速运行

环境要求：Python 3.10 及以上、联网电脑、VS Code（可选）。

1. 解压整个文件夹，使用 VS Code 打开本目录。
2. 打开 VS Code 终端，执行：

   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   python -m pip install -r requirements.txt
   ```

   如果 PowerShell 不允许激活脚本，可直接在终端使用：
   `.venv\Scripts\python.exe -m pip install -r requirements.txt`
   并在后续启动命令中也使用 `.venv\Scripts\python.exe`。

3. 在项目根目录复制 `.env.example` 为 `.env`，根据所选平台填写密钥：

   ```dotenv
   DEEPSEEK_API_KEY=你的密钥
   QWEN_API_KEY=你的密钥
   ```

   只需配置要使用的平台。不要把真实 Key 提交给老师或传到公开代码库。
   千问不同地域/业务空间需要设置与控制台一致的 `QWEN_BASE_URL`。

4. 启动：

   ```powershell
   python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
   ```

5. 浏览器打开 **http://127.0.0.1:8000**，上传一张图片，选择模型后点「开始 AI 风险检测」。

**没有 API Key**：可以打开网页、浏览静态示意报告、运行测试；不能进行真实 AI 识别。

## 三、让手机打开网页

手机与 Windows 电脑连接同一个可信 Wi-Fi。

1. 电脑运行 `ipconfig`，查看 Wi-Fi 的 IPv4 地址（例如 `192.168.1.8`）。
2. 将启动命令中的 `--host 127.0.0.1` 改成 `--host 0.0.0.0` 后重启。
3. 手机打开 `http://你的电脑IP:8000`，例如 `http://192.168.1.8:8000`。
4. 如打不开，检查 Windows 防火墙和网络隔离；不要为了完成作业直接暴露公网端口。

**浏览器摄像头权限限制**：实时摄像头 `getUserMedia()` 需要 HTTPS 或 localhost；
手机通过普通局域网 HTTP 地址访问电脑时通常不满足要求。
此时可尝试网页「手机拍照」（系统文件选择器，行为受手机浏览器影响）或上传相册图片。
若必须在手机网页中实时取景，请配置可信 HTTPS（例如可信反向代理或校内 HTTPS 部署）。

## 四、目录说明

```text
楼道消防安全隐患智能识别系统/
├── backend/
│   ├── main.py          # FastAPI 接口与页面路由
│   ├── imaging.py       # 图片检查与压缩
│   ├── vision.py        # DeepSeek / Qwen 多模态 API
│   └── risk.py          # 五级风险规则及建议
├── frontend/
│   ├── index.html       # 页面结构
│   ├── style.css        # 页面样式
│   └── app.js           # 拍照、上传、展示结果
├── tests/
│   └── test_submission.py
├── docs/                # 报告、测试记录、答辩提纲、界面预览
├── .env.example         # API Key 配置模板（不含真实密钥）
├── requirements.txt     # Python 依赖
├── 启动项目.bat          # Windows 双击启动（先安装依赖）
└── README.md
```

## 五、项目 API

- `GET /`：项目网页
- `GET /api/status`：两个模型的名称及是否配置密钥（不返回密钥）
- `POST /api/analyze`：`multipart/form-data`，图片字段 `image`，模型字段 `provider`（`deepseek` 或 `qwen`）

成功 JSON 示例（**示例，不是实际识别结果**）：

```json
{
  "risk_level": "中等风险",
  "description": "楼道内有大量纸箱",
  "evidence": ["纸箱堆积占用通道"],
  "suggestion": "尽快清理大量堆积物与可燃物，恢复通行宽度；必要时联系物业处理。",
  "is_corridor": true,
  "provider": "qwen",
  "model": "qwen3-vl-flash",
  "is_demo": false
}
```

## 六、风险规则

1. **非楼道**：图片与楼道/疏散通道无关，或无法判断是不是通道。
2. **高风险**：发现电动车、电瓶、飞线充电等起火隐患。
3. **中等风险**：严重阻塞通行或堆积大量纸箱、木质家具等可燃物。
4. **低风险**：少量堆物，不严重影响通行。
5. **无隐患**：楼道整洁，无堆物。

同一图片如果触发多个条件，从高到低取最高优先级。
风险规则的确定性不意味着 AI 对物品的识别一定准确，仍需现场复核。

## 七、测试

```powershell
python -m pytest -q
```

测试覆盖风险规则全部布尔组合、模型 JSON 校验、错误图片处理、API 通路、两家模型的**模拟 HTTP 请求**。
测试使用假 Key 和模拟服务响应，不消耗真实模型额度，也不代表真实图片的检测准确率。

## 八、注意事项

- 模型识别需要联网、对应平台账号、有效 API Key 和可用额度。
- 图片会送往所选模型平台；服务端不主动保存原始上传照片，请勿上传敏感隐私信息。
- 图片中的隐患可能被遮挡，AI 可能误报和漏报，不能替代消防工作人员现场检查。
- 项目为课程演示系统，没有身份认证、速率限制或公网安全加固，仅供本地或可信局域网使用。
- 模型 API、支持地域和配额可能变化，以各平台官方文档为准。

## 九、课程案例的对应关系

老师《案例-多模态内容理解.ipynb》的 Qwen2.5-VL 图文问答部分，展示了用视觉模型理解照片；
本项目把本地视觉推理升级为多模态在线 API，并加上网页拍照、FastAPI 和 Python 风险分级。
具体对照见 `docs/课程案例对应关系.md`。
