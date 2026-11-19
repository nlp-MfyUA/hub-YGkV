#!/bin/sh
# 构建镜像：先同步作业1 的代码，再 docker build
set -e

HERE=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=${IMAGE:-week15-sentiment-chain:1.0}
PIP_INDEX=${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}

sh "$HERE/scripts/sync_app.sh"

echo "\n=== docker build -t $IMAGE ==="
docker build \
  --build-arg PIP_INDEX_URL="$PIP_INDEX" \
  -t "$IMAGE" \
  "$HERE"

echo "\n=== 镜像信息 ==="
docker images "$IMAGE"
