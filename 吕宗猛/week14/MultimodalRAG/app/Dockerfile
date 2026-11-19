FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
COPY app/requirements.txt /app/requirements.txt
RUN HTTP_PROXY=$HTTP_PROXY HTTPS_PROXY=$HTTPS_PROXY pip install -i ${PIP_INDEX_URL} -r /app/requirements.txt
COPY app /app/app
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
