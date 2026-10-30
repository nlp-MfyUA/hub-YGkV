# 测试套件

所有脚本均以**项目相对路径**运行，不依赖系统临时目录。

## 前置

- 后端已启动：`python app.py`（默认 `http://127.0.0.1:8000`）
- 本机安装 Chrome（`C:\Program Files\Google\Chrome\Application\chrome.exe`，
  可用环境变量 `CHROME_PATH` 覆盖）
- Python 3.11+（需 `pillow`；仅合成图生成与稳定性测量用到）

## 脚本

| 脚本 | 作用 | 输出 |
|---|---|---|
| `test_api.py` | 健康检查 + 全样本图分类回归，断言用「可接受判定集合」 | `results.json` |
| `test_e2e.py` | CDP 驱动真实 Chrome，覆盖**上传**与**拍照**两条链路 | `e2e_result.json`、`e2e_result.png` |
| `measure_stability.py [N]` | 同一图重复 N 次，统计判定分布与耗时区间 | `stability.json` |
| `make_synthetic.py` | 生成「楼道 + 电动车」合成验证图 | `samples/synthetic_corridor_ebike.jpg` |

## 用法

```powershell
cd 作业1-楼道风险识别

# 全样本回归
python tests\test_api.py

# 重复 6 次看稳定性
python tests\test_api.py --repeat=6

# 只测一张
python tests\test_api.py tests\samples\corridor_clutter_high_boxes.jpg

# 前端端到端（上传 + 拍照）
python tests\test_e2e.py

# 稳定性专项
python tests\measure_stability.py 8
```

## 说明

- `test_e2e.py` 会用到 `tests/.chrome-profile/` 作为 Chrome 独立配置目录（已在 `.gitignore` 排除）。
- `results.json` / `e2e_result.json` / `stability.json` 均为**实测输出**，可随时重跑覆盖。
- 测试结论与已知缺口见 `RESULTS.md`，样本图出处见 `SAMPLES.md`。
