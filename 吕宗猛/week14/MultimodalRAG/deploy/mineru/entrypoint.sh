#!/bin/sh
set -eu

echo "[mineru] ensuring basic models..."
mineru-kit models download --tier basic || echo "[mineru] model download failed; API server may retry"

echo "[mineru] starting api-server on :8000 (tier=basic)"
mineru-kit api-server --host 0.0.0.0 --port 8000 --tier basic &
API_PID=$!

for i in $(seq 1 180); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=3)" >/dev/null 2>&1; then
    echo "[mineru] api-server ready"
    break
  fi
  sleep 2
done

echo "[mineru] starting file-parse-server on :8003"
mineru-kit file-parse-server --api-url http://127.0.0.1:8000 --host 0.0.0.0 --port 8003 &
FP_PID=$!

trap 'kill "$API_PID" "$FP_PID" 2>/dev/null || true' TERM INT
wait "$API_PID" "$FP_PID"
