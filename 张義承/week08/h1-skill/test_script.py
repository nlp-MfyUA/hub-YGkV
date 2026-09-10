#!/usr/bin/env python3
"""测试脚本：验证权限和依赖检查"""

import os
import sys

# 本地已有的依赖
import aiohttp
import numpy as np
import requests

# 本地没有的依赖（用于测试缺失提示）
import missing_module_abc
import nonexistent_pkg_xyz

print("Hello, World!")
print(f"Python version: {sys.version}")
print(f"Script path: {__file__}")
