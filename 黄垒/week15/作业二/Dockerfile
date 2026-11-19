# 作业二：把作业1 的 openai-agents 版本打成镜像
#
# 一个镜像 = 四个角色（进程1 / 进程2 / 后端 / 前端），
# 具体跑哪个由环境变量 ROLE 决定（entrypoint.sh 里分发），
# 这样「四个进程」在容器里也是四个独立的容器，而不是一个容器里塞四份 python。

FROM python:3.12-slim

LABEL org.opencontainers.image.title="week15-sentiment-chain" \
      org.opencontainers.image.description="四进程情感陪伴链路（openai-agents 版）" \
      org.opencontainers.image.version="1.0.0"

# 国内网络下换 pip 源（构建时可覆盖：--build-arg PIP_INDEX_URL=...）
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8

WORKDIR /app

# 先装依赖，再把代码 COPY 进来：改代码不会失效依赖层，重建只要几秒
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app/common ./common
COPY app/agents_version ./agents_version
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# 三个服务端口；前端容器不监听端口，只用 stdin/stdout
ENV BACKEND_PORT=8100 \
    SENTIMENT_PORT=8101 \
    REPLY_PORT=8102 \
    ROLE=backend

EXPOSE 8100 8101 8102

HEALTHCHECK --interval=20s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8100'), timeout=2)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
