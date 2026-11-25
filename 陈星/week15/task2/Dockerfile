FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLM_MODE=mock

WORKDIR /app

COPY requirements-docker.txt ./
RUN python -m pip install --no-cache-dir -r requirements-docker.txt

COPY common/*.py ./common/
COPY openai_agents_impl/*.py ./openai_agents_impl/

USER 10001:10001

ENTRYPOINT ["python", "-m", "openai_agents_impl.run_all"]
