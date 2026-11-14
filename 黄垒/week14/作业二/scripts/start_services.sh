#!/bin/bash
# 拉起所有依赖服务（幂等：端口已在监听就跳过）
# 用法：bash scripts/start_services.sh
set -u

E=/usr/local/miniconda3/envs/py312/bin
SW=/workspace/software
LOG=/tmp/rag_services
mkdir -p $LOG

port_open() { ss -lnt 2>/dev/null | grep -q ":$1 "; }

wait_port() {
  local p=$1 n=${2:-40}
  for _ in $(seq 1 "$n"); do
    port_open "$p" && return 0
    sleep 1
  done
  return 1
}

echo "== 1/6 MySQL =="
if port_open 3306; then
  echo "   已在运行"
else
  mkdir -p /var/run/mysqld && chown mysql:mysql /var/run/mysqld 2>/dev/null
  nohup mysqld --user=mysql --datadir=/var/lib/mysql \
    --socket=/var/run/mysqld/mysqld.sock --port=3306 > $LOG/mysqld.log 2>&1 &
  wait_port 3306 30 && echo "   已启动" || echo "   启动失败，见 $LOG/mysqld.log"
fi

echo "== 2/6 Redis =="
if port_open 6379; then
  echo "   已在运行"
else
  nohup $SW/redis-7.2.5/src/redis-server $SW/redis-7.2.5/redis.conf > $LOG/redis.log 2>&1 &
  wait_port 6379 20 && echo "   已启动" || echo "   启动失败"
fi

echo "== 3/6 Kafka =="
if port_open 9092; then
  echo "   已在运行"
else
  nohup env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    $SW/kafka_2.13-4.4.0/bin/kafka-server-start.sh \
    $SW/kafka_2.13-4.4.0/config/server.properties > $LOG/kafka.log 2>&1 &
  wait_port 9092 60 && echo "   已启动" || echo "   启动失败，见 $LOG/kafka.log"
fi

echo "== 4/6 Elasticsearch =="
if port_open 9200; then
  echo "   已在运行"
else
  su esuser -c "cd $SW/elasticsearch-8.15.3 && nohup env -u HTTP_PROXY -u HTTPS_PROXY \
    -u http_proxy -u https_proxy bin/elasticsearch > $LOG/es.log 2>&1 &"
  wait_port 9200 90 && echo "   已启动" || echo "   启动失败，见 $LOG/es.log"
fi

echo "== 5/6 MinerU api-server（常驻，模型只加载一次）=="
if port_open 8100; then
  echo "   已在运行"
else
  export PATH=$E:$PATH
  cd /workspace
  nohup env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    $E/mineru-kit api-server --host 127.0.0.1 --port 8100 \
    --tier advanced --preload-models > $LOG/mineru.log 2>&1 &
  # 第一次要加载 MinerU2.5 权重，给足时间
  wait_port 8100 150 && echo "   已启动" || echo "   启动失败，见 $LOG/mineru.log"
fi

echo "== 6/6 vLLM（Qwen3.5-0.8B，多模态）=="
if port_open 8001; then
  echo "   已在运行"
else
  export PATH=$E:$PATH
  cd /workspace
  nohup env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    $E/vllm serve models/Qwen3.5-0.8B/ \
    --served-model-name qwen3.5-0.8b \
    --port 8001 \
    --gpu-memory-utilization 0.32 \
    --max-model-len 16384 \
    --limit-mm-per-prompt '{"image":4,"video":0}' \
    --trust-remote-code > $LOG/vllm.log 2>&1 &
  wait_port 8001 180 && echo "   已启动" || echo "   启动失败，见 $LOG/vllm.log"
fi

echo
echo "端口状态："
ss -lntp 2>/dev/null | grep -E ':(3306|6379|9092|9200|8100|8001) ' | sed 's/^/   /'
