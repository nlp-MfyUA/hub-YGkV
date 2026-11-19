#!/bin/sh
# 用镜像起「四个进程 = 四个容器」。
#
#   sh scripts/run.sh up       # 起进程1 / 进程2 / 后端（映射 8100-8102）
#   sh scripts/run.sh demo     # 在容器里跑前端进程的内置用例
#   sh scripts/run.sh cli      # 前端进程交互模式（Ctrl+C 退出）
#   sh scripts/run.sh logs     # 看三个服务容器的日志
#   sh scripts/run.sh down     # 停掉并清理
set -e

HERE=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=${IMAGE:-week15-sentiment-chain:1.0}
NET=${NET:-week15-net}

# 从 week15/.env 读 Key（不在命令行里硬编码）
if [ -f "$HERE/../.env" ]; then
  set -a
  . "$HERE/../.env"
  set +a
fi

if [ -z "${LLM_API_KEY:-}" ]; then
  echo "请先在 week15/.env 里配置 LLM_API_KEY，或 export LLM_API_KEY=..." >&2
  exit 1
fi

ENVS="-e LLM_API_KEY=$LLM_API_KEY -e LLM_BASE_URL=${LLM_BASE_URL:-https://api.deepseek.com} -e LLM_MODEL=${LLM_MODEL:-deepseek-chat}"
SERVICES="w15-sentiment w15-reply w15-backend"

wait_health() {
  echo "等待后端就绪…"
  i=0
  while [ $i -lt 60 ]; do
    if docker exec w15-backend python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8100/health', timeout=2)" >/dev/null 2>&1; then
      echo "后端 OK"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "后端启动超时，看日志：sh scripts/run.sh logs" >&2
  return 1
}

case "${1:-up}" in
  up)
    docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
    docker rm -f $SERVICES >/dev/null 2>&1 || true

    docker run -d --name w15-sentiment --network "$NET" --network-alias sentiment \
      -p 8101:8101 -e ROLE=sentiment -e PORT=8101 $ENVS "$IMAGE" >/dev/null
    docker run -d --name w15-reply --network "$NET" --network-alias reply \
      -p 8102:8102 -e ROLE=reply -e PORT=8102 $ENVS "$IMAGE" >/dev/null
    docker run -d --name w15-backend --network "$NET" --network-alias backend \
      -p 8100:8100 -e ROLE=backend -e PORT=8100 \
      -e SENTIMENT_URL=http://sentiment:8101 -e REPLY_URL=http://reply:8102 $ENVS "$IMAGE" >/dev/null

    wait_health
    docker ps --filter name=w15- --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    echo "\n网页前端： http://127.0.0.1:8100"
    ;;
  demo)
    docker run --rm -i --network "$NET" -e ROLE=frontend \
      -e BACKEND_URL=http://backend:8100 $ENVS "$IMAGE" --demo
    ;;
  cli)
    docker run --rm -i -t --network "$NET" -e ROLE=frontend \
      -e BACKEND_URL=http://backend:8100 $ENVS "$IMAGE"
    ;;
  logs)
    docker logs --tail 40 w15-backend
    docker logs --tail 20 w15-sentiment
    docker logs --tail 20 w15-reply
    ;;
  down)
    docker rm -f $SERVICES >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    echo "已清理容器和网络"
    ;;
  *)
    echo "用法：sh scripts/run.sh [up|demo|cli|logs|down]" >&2
    exit 2
    ;;
esac
