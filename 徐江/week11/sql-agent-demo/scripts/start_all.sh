#!/usr/bin/env bash
# ============================================================
#  SQL Agent 一键启动：后端 + 前端（同一终端，Ctrl+C 一起停止）
#
#  用法：
#    ./start_all.sh          正常模式（DeepSeek，需配置 Key）
#    ./start_all.sh --mock   离线 mock 模式（无需 Key）
#
#  环境变量：
#    BACKEND_PORT=8000   后端端口（默认 8000）
#    FRONTEND_PORT=8501  前端端口（默认 8501）
# ============================================================
set -euo pipefail

USE_MOCK=""
if [[ "${1:-}" == "--mock" ]]; then USE_MOCK=1; fi
if [[ -n "$USE_MOCK" ]]; then export LLM_PROVIDER=mock; fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-8501}"

# 切换到项目根目录（脚本位于 scripts/ 下）
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- 激活 conda 环境 py312 ----
CONDA_BASE="$(conda info --base 2>/dev/null || true)"
if [[ -z "$CONDA_BASE" && -d "/d/ProgramData/anaconda3" ]]; then
    CONDA_BASE="/d/ProgramData/anaconda3"
fi
if [[ -z "$CONDA_BASE" ]]; then
    echo "[ERROR] 未找到 conda，请先激活 py312 环境再运行本脚本" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate py312

# ---- 修复无效的 SSL_CERT_FILE ------------------------------------------
# conda activate 可能把 SSL_CERT_FILE 指向不存在的路径（本机 py312 即如此：
# 激活脚本指向 <env>/ssl/cacert.pem，实际 cacert 在 <env>/Library/ssl/ 下），
# 会导致 openai/httpx 在创建客户端时直接崩溃。此处校验并自愈。
if [ -n "${SSL_CERT_FILE:-}" ] && [ ! -f "$SSL_CERT_FILE" ]; then
    for _candidate in "$CONDA_PREFIX/Library/ssl/cacert.pem" "$CONDA_PREFIX/ssl/cacert.pem"; do
        _candidate="${_candidate//\\//}"
        if [ -f "$_candidate" ]; then
            export SSL_CERT_FILE="$_candidate"
            echo "[fix] SSL_CERT_FILE 原路径无效，已重定向到: $_candidate"
            break
        fi
    done
    if [ ! -f "${SSL_CERT_FILE:-}" ]; then
        unset SSL_CERT_FILE
        echo "[fix] SSL_CERT_FILE 原路径无效且未找到替代 cacert，已清除该变量"
    fi
fi

# 退出时确保子进程一起结束
cleanup() {
    echo ""
    echo "正在停止 SQL Agent 服务 ..."
    [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ -n "$USE_MOCK" ]]; then MODE_TEXT="mock 离线模式（无需 API Key）"; else MODE_TEXT="DeepSeek 真实 API（需配置 Key）"; fi

cat <<EOF
============================================================
  SQL Agent 一键启动
  工作目录 : $(pwd)
  运行模式 : $MODE_TEXT
  后端     : http://127.0.0.1:$BACKEND_PORT  （API 文档 /docs）
  前端     : http://localhost:$FRONTEND_PORT
  停止     : Ctrl+C（两个服务一起停止）
============================================================

EOF

uvicorn backend.app:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!

# 等待后端就绪后再拉起前端，避免前端首次连接检查失败；
# 若后端进程提前退出（如端口占用、配置错误），立即报错而不是干等超时。
BACKEND_READY=""
for _ in $(seq 1 30); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "[ERROR] 后端进程已退出，启动失败。请检查上方日志（常见原因：端口被占用、配置错误）。" >&2
        exit 1
    fi
    if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
        BACKEND_READY=1
        echo "[ok] 后端已就绪"
        break
    fi
    sleep 0.5
done
if [ -z "$BACKEND_READY" ]; then
    echo "[ERROR] 后端在 15 秒内未就绪，请检查上方日志。" >&2
    exit 1
fi

streamlit run frontend/app.py --server.port "$FRONTEND_PORT" --browser.gatherUsageStats false &
FRONTEND_PID=$!

echo "[ok] 前端已启动（PID=$FRONTEND_PID），浏览器访问 http://localhost:$FRONTEND_PORT"
wait
