# 测试报告 · 楼道消防风险识别

> 数据均为**实测**（直接调用本机后端 `http://127.0.0.1:8000`），原始输出见
> `tests/results.json`、`tests/stability.json`、`tests/illumination_study.json`、`tests/e2e_result.json`。
> 复现命令见 `tests/README.md`。

## 1. 环境

| 项 | 值 |
|---|---|
| 采集日期 | 2026-10-28 |
| 模型 | `cn:deepseek-v4.1-flash`（响应回显 `deepseek-v4.1-flash`） |
| 网关 | `http://192.168.124.88:7863/v1`（OpenAI 兼容） |
| 后端 | FastAPI + urllib 直调，零第三方 SDK |
| 前端 | 单页无构建，Chrome headless 驱动验证 |
| 主机 | Windows / Python 3.14.6 / Chrome 156.0.8078.49 |

## 2. 分类准确率（11 张样本，各调用 1 次）

| 样本图 | 场景 | 可接受判定 | 实测 | 结果 |
|---|---|---|---|---|
| `corridor_clutter_high_boxes.jpg` | 楼道口大量纸箱、木质家具堆积 | 中风险 | 中风险 | ✅ |
| `corridor_door_clutter.jpg` | 单元门外堆放置物架、塑料筐 | 低风险 / 中风险 | 低风险 | ✅ |
| `corridor_scooter_chair.jpg` | 楼道内滑板车、椅子、购物袋 | 低风险 | 低风险 | ✅ |
| `stairwell_bicycle.jpg` | 楼梯间停放自行车 | 低风险 | 低风险 | ✅ |
| `non_corridor_pingpong.jpg` | 室内乒乓球活动 | 非楼道 | 非楼道 | ✅ |
| `noncorridor_black_frame.jpg` | 全黑图 | 非楼道 | 非楼道 | ✅ |
| `noncorridor_text_shortreview.jpg` | 文字截图 | 非楼道 | 非楼道 | ✅ |
| `noncorridor_text_icon.jpg` | 图标截图 | 非楼道 | 非楼道 | ✅ |
| `noncorridor_unreadable.jpg` | 不可辨图 | 非楼道 | 非楼道 | ✅ |
| `corridor_ebike_a/b/c.jpg` | 商业区檐廊（真实照片裁切） | 非楼道 | 非楼道 | ✅ |
| `source_ebike_scooters_ccbysa4.jpg` | 室外电动车停放 | 非楼道 | 非楼道 | ✅ |
| `synthetic_corridor_ebike.jpg` | 楼道 + 电动车（合成） | 中风险 / 高风险 | 随调用变化 | ⚠️ 见 §4 |

**五档覆盖情况**：中风险 ✅、低风险 ✅、非楼道 ✅、高风险 ✅（可达，见 §4）、
无风险 ❌ 未取得样本（公开渠道难获取「干净无堆物」的楼道照）。

## 3. 判定稳定性（每图 6 次重复，`tests/stability.json`）

| 样本图 | 6 次分布 | 结论 |
|---|---|---|
| `corridor_clutter_high_boxes.jpg` | 中风险 ×6 | 稳定 |
| `corridor_scooter_chair.jpg` | 低风险 ×6 | 稳定 |
| `non_corridor_pingpong.jpg` | 非楼道 ×6 | 稳定 |
| `corridor_door_clutter.jpg` | 低风险 ×4、中风险 ×1、非楼道 ×1 | **有漂移**（暗光图） |
| `synthetic_corridor_ebike.jpg` | 中风险 ×5、高风险 ×1 | **有漂移**（合成痕迹） |

**漂移成因**：模型带思维链，`temperature=0.1` 下同一图仍可能给出不同档位。
暗光图（`corridor_door_clutter.jpg` 原图均值亮度低）漂移更明显。

## 4. 高风险档的验证现状

- 高风险标准已写入提示词（见 `app.py` 的 `PROMPT`），后端强制校验该枚举值。
- 实测**观察到**模型输出「高风险」：合成样本在 2026-10-28 的一次 8 连测中 7 次判高风险，
  另一次 6 连测中 1 次判高风险。
- **该样本无法稳定复现**：合成图带有拼接痕迹，模型会在「中风险（看到车+杂物）」与
  「高风险（触发电动车规则）」之间摇摆。
- **未取得真实「楼道内停放电动车」照片**：已尝试 Wikimedia Commons（分类树 + 全文检索）、
  政务消防 PDF（该 PDF 仅 8 张图，已全部提取）、HuggingFace 数据集检索，均未命中；
  现实原因是这类照片多见于中文新闻与政务通报，可自由获取的公开样本极少。
- 结论：**高风险档在实现与模型侧均已打通**，但本次缺少可稳定复现的真实样本，
  属**已知验证缺口**，如实记录而非用合成图掩盖。

## 5. 亮度归一化对照实验（`tests/illumination_study.json`）

同一张图分别以 原始 / 固定提亮 1.6 / 按均值自适应提亮 三种方式送入模型，各 6 次：

| 样本图 | 原始 | 提亮 1.6 | 自适应提亮 |
|---|---|---|---|
| `corridor_door_clutter.jpg` | 低风险 4、中风险 1、非楼道 1 | 低风险 5、中风险 1 | 低风险 3、中风险 3 |
| `corridor_scooter_chair.jpg` | 低风险 6 | 低风险 6 | 低风险 6 |
| `synthetic_corridor_ebike.jpg` | 中风险 5、高风险 1 | 高风险 5、中风险 1 | 中风险 6 |

**结论**：n=6 下三种处理的差异落在噪声范围内，自适应提亮反而更差。
因此**未据此修改前端处理逻辑**——避免拿弱证据改产品行为。

## 6. 前端端到端（`tests/e2e_result.json`）

### 上传链路
CDP 注入文件 → `change` 事件 → 客户端压缩 → `POST /api/recognize` → 结果卡片渲染
→ localStorage 历史写入（含缩略图）。

- 结果卡片显示等级、理由、风险元素 chips、耗时与 token
- 页面 `scrollWidth == clientWidth`（无横向溢出）
- 历史记录条数递增正确

### 拍照链路
Chrome 假摄像头（`--use-fake-device-for-media-stream`）：

- `getUserMedia` 成功取流 **1920×1080**，按钮态切换为「✕ 关闭摄像头」，拍摄按钮解禁
- 点击拍摄 → canvas 截帧为 JPEG dataURL（实测 14,187 字节）→ 预览显示 → 摄像头自动关闭
- 提交识别 → 2.05 s 返回「非楼道」（假摄像头画面为绿色抽象图形，判定正确）

## 7. 接口与健壮性

| 检查项 | 结果 |
|---|---|
| `GET /api/health` | 200，返回模型名与网关地址 |
| `GET /api/health`（HTTPS :8443，自签证书） | 200（curl -k 验证；PowerShell 5.1 需回调放行证书） |
| 首页静态页 | 200 |
| `/favicon.svg` | 200（已消除 404 控制台报错） |
| 非法 base64 → 400 | ✅ |
| 思维链超预算（`finish_reason=length`） | **已修复**：见下 |

### 本轮修复的两个真实缺陷

1. **`max_tokens` 不足导致 502**
   模型思维链超出预算时 `finish_reason=length`、最终 `content` 为空，后端返回 502。
   原实现固定 `max_tokens=2000` 且无重试。
   **修复**：`max_tokens` 提至 3000（可由 `MAX_TOKENS` 配置），
   并在命中 `length` 时**自动加倍重试**（上限 `MAX_TOKENS_CEILING=12000`，最多 3 次）。
   修复后同一张此前必失败的图 **连续 8 次调用零 502**。

2. **`run.ps1` 在 Windows PowerShell 5.1 下语法错误**
   文件为 UTF-8 无 BOM，中文注释被按 GBK 解码后吞掉换行，把 `param(` 并入注释行。
   **修复**：改存 UTF-8 with BOM，另提供 `启动.cmd` 双击入口。
