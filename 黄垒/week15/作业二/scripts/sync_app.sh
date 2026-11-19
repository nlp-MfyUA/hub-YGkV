#!/bin/sh
# 把「作业一 / agents_version + common」同步到本目录的 app/ 下。
# 为什么要有这一步：docker build 的上下文里不希望出现中文路径和 .venv，
# 同步一份 ASCII 路径的副本进去，构建稳定、也快。
set -e

HERE=$(cd "$(dirname "$0")/.." && pwd)
SRC="$HERE/../作业一"

test -d "$SRC/agents_version" || { echo "找不到 $SRC/agents_version"; exit 1; }

rm -rf "$HERE/app"
mkdir -p "$HERE/app"
cp -r "$SRC/common" "$HERE/app/common"
cp -r "$SRC/agents_version" "$HERE/app/agents_version"

find "$HERE/app" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$HERE/app" -name "*.pyc" -delete 2>/dev/null || true

echo "已同步：$HERE/app"
echo "  - $(ls "$HERE/app/common" | tr '\n' ' ')"
echo "  - $(ls "$HERE/app/agents_version" | tr '\n' ' ')"
