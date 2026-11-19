# syntax=docker/dockerfile:1
# 单镜像同时包含前端与后端，适合课堂演示或单容器部署。
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_ENV=1 \
    BACKEND_URL=http://127.0.0.1:8623

WORKDIR /app

# 只复制安装结果，不把 pip 缓存、编译器带进最终镜像
COPY --from=builder /install /usr/local
COPY backend ./backend
COPY frontend ./frontend
COPY seed ./seed
COPY run_all.py ./run_all.py

RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

# 入口以 root 启动：复制种子库并 chown 到 appuser 后自动降权

EXPOSE 8613 8623

# 同时启动后端（8623）与前端（8613）
CMD ["python", "run_all.py"]