"""前端无浏览器全流程验证（Streamlit AppTest）。

运行前确保：
  1. 后端已在 mock 模式启动：LLM_PROVIDER=mock uvicorn backend.app:app --port 8000
  2. 在本项目根目录执行：python dev/test_frontend.py

验证点：页面初始渲染无异常 → 侧边栏连接检查 → 运行工作流（含重试回路）
→ 加载数据库结构。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

QUESTION = "所有已完成订单的总金额是多少？"  # mock 下会触发「校验失败 → 改写」重试


def _find(elements, label_contains: str):
    for element in elements:
        if label_contains in (element.label or ""):
            return element
    return None


def main() -> int:
    at = AppTest.from_file(
        str(PROJECT_ROOT / "frontend" / "app.py"), default_timeout=120
    )
    at.run()
    if at.exception:
        print("❌ 初始渲染异常:", at.exception)
        return 1
    print("✅ 初始渲染无异常")

    # 1. 侧边栏「检查连接」
    button = _find(at.button, "检查连接")
    if button is None:
        print("❌ 未找到「检查连接」按钮")
        return 1
    button.click().run()
    if at.exception:
        print("❌ 检查连接异常:", at.exception)
        return 1
    success = [s.value for s in at.success]
    print("✅ 检查连接 ->", success[0] if success else "（无 success 消息）")

    # 2. 输入问题并运行工作流
    text_input = _find(at.text_input, "输入你的自然语言问题")
    if text_input is None:
        print("❌ 未找到问题输入框")
        return 1
    text_input.set_value(QUESTION)
    at.run()
    run_button = _find(at.button, "运行工作流")
    if run_button is None:
        print("❌ 未找到「运行工作流」按钮")
        return 1
    run_button.click().run()
    if at.exception:
        print("❌ 运行工作流异常:", at.exception)
        return 1
    banners = [s.value for s in at.success] + [e.value for e in at.error]
    print("✅ 工作流结果横幅:", banners[-1] if banners else "（无）")

    # 3. 校验关键渲染产物
    codes = [c.value for c in at.code]
    has_final_sql = any("SUM(" in code for code in codes)
    print("✅ 最终 SQL 已渲染:", has_final_sql)
    expanders = [e.label for e in at.expander]
    retry_visible = any("SQL 改写" in label and "第 2 次尝试" in label for label in expanders)
    print("✅ 重试回路可见（SQL 改写 · 第 2 次尝试）:", retry_visible)

    # 4. 加载数据库结构
    schema_button = _find(at.button, "加载 / 刷新数据库结构")
    if schema_button is None:
        print("❌ 未找到「加载数据库结构」按钮")
        return 1
    schema_button.click().run()
    if at.exception:
        print("❌ 加载 schema 异常:", at.exception)
        return 1
    print("✅ 数据库结构已加载，expander 数:", len(at.expander))

    ok = has_final_sql and retry_visible
    print("\n结果:", "✅ 前端全流程验证通过" if ok else "❌ 存在未通过项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
