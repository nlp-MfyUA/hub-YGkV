#!/bin/bash
# 启动本项目的两个进程：解析 worker + Web 服务
# 用法：bash scripts/start_app.sh [worker数量]
set -u

DIR=/workspace/hl_test/rag_kafka_multimodal
PY=/usr/local/miniconda3/envs/py312/bin/python
N=${1:-1}
mkdir -p "$DIR/logs"

cd "$DIR" || exit 1

# 清理旧进程，避免端口/消费组重复
pkill -f "parse_worker.py run" 2>/dev/null
pkill -f "api_server.py" 2>/dev/null
sleep 1

# 机器上配了 HTTP_PROXY；本机服务一律走裸 socket
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

if [ ! -f .env ]; then cp .env.example .env; fi

echo "启动 $N 个 parse worker（消费组 rag-parser，topic 3 分区，最多 3 个实例并行）"
for i in $(seq 1 "$N"); do
  nohup "$PY" parse_worker.py run > "logs/worker-$i.log" 2>&1 &
  echo "  worker-$i pid=$!"
done

nohup "$PY" api_server.py > logs/api.log 2>&1 &
echo "  api pid=$!"

sleep 3
echo
echo "健康检查："
curl -s --noproxy '*' http://127.0.0.1:8080/api/health \
  | "$PY" -c "import json,sys; d=json.load(sys.stdin); print('  kafka:', d['kafka']['ok'], '| es:', d['es']['ok'], '| mysql:', d['mysql']['ok'], '| mineru:', d['mineru'].get('ok'), '| llm:', d['llm'].get('ok'))"
echo
echo "打开 http://127.0.0.1:8080"
