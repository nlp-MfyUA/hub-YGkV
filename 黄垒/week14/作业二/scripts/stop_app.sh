#!/bin/bash
# 停止本项目的进程（不动 Kafka / ES / MySQL / MinerU / vLLM）
set -u
pkill -f "parse_worker.py run" 2>/dev/null && echo "worker 已停止" || echo "worker 未运行"
pkill -f "api_server.py" 2>/dev/null && echo "api 已停止" || echo "api 未运行"
ss -lnt 2>/dev/null | grep -q ':8080 ' && echo "警告：8080 仍被占用" || echo "8080 已释放"
