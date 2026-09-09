---
name: zyc-skill01
description: Use when user asks how to run a python script, or encounters missing dependency errors, or needs to check python script permissions
version: "1.0.0"
license: MIT
---

# Python 脚本执行检查

## 概述

在运行 Python 脚本之前，自动检查执行权限和依赖是否满足，确保脚本能顺利执行。

## 何时使用

- 用户询问如何执行某个 Python 脚本
- 用户运行脚本后报 `ModuleNotFoundError`、`ImportError` 等依赖错误
- 用户不确定当前环境是否满足脚本的运行条件

## 核心模式

1. **检查执行权限**
   ```bash
   ls -l /path/to/script.py
   ```
   - 无执行权限 → 提示并生成 `chmod +x /path/to/script.py`

2. **收集脚本依赖**
   - 读取脚本头部 `import` / `from ... import` 语句
   - 或提取 `requirements.txt`、`pyproject.toml` 中的依赖

3. **对比当前环境**
   ```bash
   python -c "import module_name"  # 逐个检查
   ```
   - 列出已安装和缺失的依赖

4. **生成安装命令**
   ```bash
   pip install missing_module1 missing_module2
   ```

## 快速参考

| 场景 | 命令 |
|------|------|
| 检查脚本权限 | `ls -l script.py` |
| 添加执行权限 | `chmod +x script.py` |
| 检查单个依赖 | `python -c "import xxx"` |
| 批量安装缺失依赖 | `pip install module1 module2` |
| 查看已安装包 | `pip list` |

## 常见错误

| 错误 | 正确做法 |
|------|---------|
| 直接运行未检查权限 | 先 `ls -l` 确认有执行权限再运行 |
| 依赖缺失直接运行 | 先用 `python -c "import xxx"` 逐个验证依赖 |
| 缺失多个依赖逐个安装 | 一次性 `pip install m1 m2 m3` 批量安装 |
