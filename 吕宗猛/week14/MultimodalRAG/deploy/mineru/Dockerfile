FROM python:3.11-slim
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MINERU_MODEL_SOURCE=modelscope
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} "mineru==4.2.1"
COPY entrypoint.sh /usr/local/bin/mineru-entrypoint.sh
RUN chmod +x /usr/local/bin/mineru-entrypoint.sh
EXPOSE 8000 8003
ENTRYPOINT ["/usr/local/bin/mineru-entrypoint.sh"]
