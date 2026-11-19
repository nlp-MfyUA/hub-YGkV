#!/bin/sh
# 一个镜像，四种角色：靠 ROLE 环境变量决定起哪个进程。
# 额外参数会透传给 python -m（比如前端容器的 --demo）。
set -e

ROLE="${ROLE:-backend}"

case "$ROLE" in
  sentiment)
    exec python -m agents_version.sentiment_service
    ;;
  reply)
    exec python -m agents_version.reply_service
    ;;
  backend)
    exec python -m agents_version.backend
    ;;
  frontend)
    exec python -m common.frontend_cli "$@"
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo "未知 ROLE=$ROLE（可选：sentiment / reply / backend / frontend / shell）" >&2
    exit 2
    ;;
esac
