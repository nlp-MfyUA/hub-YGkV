#!/usr/bin/env bash
# ============================================================
#  SQL Agent 前端启动脚本（Streamlit）
#
#  用法：
#    ./start_frontend.sh               默认端口 8501
#    ./start_frontend.sh --port 8502   指定端口
#
#  前置条件：后端已在运行（start_backend.sh 或 start_all.sh）
# ============================================================
set -euo pipefail

PORT="8501"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            if [[ -n "${2:-}" ]]; then PORT="$2"; shift 2; else shift; fi
            ;;
        *)
            echo "[ERROR] 未知参数: $1" >&2
            echo "用法: $0 [--port N]" >&2
            exit 1
            ;;
    esac
done

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

cat <<EOF
============================================================
  SQL Agent 前端（Streamlit）
  工作目录 : $(pwd)
  监听端口 : $PORT
  访问地址 : http://localhost:$PORT
  默认后端 : http://127.0.0.1:8000（可在页面侧边栏修改）
============================================================

EOF

exec streamlit run frontend/app.py --server.port "$PORT" --browser.gatherUsageStats false
