ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# 依赖单独复制，代码修改时复用安装层；镜像内不存放 API Key。
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

COPY --chown=app:app common ./common
COPY --chown=app:app agents_app ./agents_app
COPY --chown=app:app run.py ./run.py
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# 同一镜像启动四个独立进程，仅对外暴露前端端口。
CMD ["python", "run.py", "--framework", "openai-agents", "--host", "0.0.0.0"]
