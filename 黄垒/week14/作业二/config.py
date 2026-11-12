#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集中配置。所有外部依赖地址、阈值都收在这里，环境变量优先。

设计上把「基础设施」和「业务参数」分开：
  基础设施：Kafka / MySQL / ES / MinerU / vLLM 的地址
  业务参数：分块长度、召回条数、送进 VLM 的图片张数与分辨率
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """极简 .env 读取（不引入 python-dotenv）：已存在的环境变量优先。"""
    p = BASE_DIR / ".env"
    if not p.exists():
        return
    for raw in p.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 目录
DATA_DIR = Path(_env("RAG_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"        # 原始 PDF
MEDIA_DIR = DATA_DIR / "media"           # 从 PDF 抽出来的图片（对外静态服务）
WORK_DIR = DATA_DIR / "work"             # MinerU 临时工作目录
ASK_IMG_DIR = DATA_DIR / "ask_images"    # 用户在对话里上传的图片
for _d in (UPLOAD_DIR, MEDIA_DIR, WORK_DIR, ASK_IMG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- Kafka
KAFKA_BOOTSTRAP = _env("KAFKA_BOOTSTRAP", "127.0.0.1:9092")
TOPIC_PARSE = _env("TOPIC_PARSE", "rag.doc.parse")          # 上传事件 → 解析任务
TOPIC_STATUS = _env("TOPIC_STATUS", "rag.doc.status")       # 解析状态变更（审计/观察）
TOPIC_DLQ = _env("TOPIC_DLQ", "rag.doc.parse.dlq")          # 重试用尽后的死信
CONSUMER_GROUP = _env("CONSUMER_GROUP", "rag-parser")
PARSE_PARTITIONS = _env_int("PARSE_PARTITIONS", 3)           # 3 分区 = 最多 3 个 worker 并行
MAX_ATTEMPTS = _env_int("MAX_ATTEMPTS", 2)                   # 首次失败后允许再投递 1 次
POLL_TIMEOUT_MS = _env_int("POLL_TIMEOUT_MS", 1000)

# ---------------------------------------------------------------- MySQL
MYSQL = {
    "host": _env("MYSQL_HOST", "127.0.0.1"),
    "port": _env_int("MYSQL_PORT", 3306),
    "user": _env("MYSQL_USER", "root"),
    "password": _env("MYSQL_PASSWORD", "Root@123456"),
    "database": _env("MYSQL_DB", "rag_hl"),
    "charset": "utf8mb4",
}

# ---------------------------------------------------------------- Elasticsearch
ES_URL = _env("ES_URL", "http://127.0.0.1:9200")
ES_INDEX = _env("ES_INDEX", "rag_chunks_v1")
ES_TIMEOUT = _env_float("ES_TIMEOUT", 10.0)

# ---------------------------------------------------------------- MinerU
MINERU_BIN = _env("MINERU_BIN", "/usr/local/miniconda3/envs/py312/bin/mineru-kit")
# 常驻解析服务；为空则 worker 直接起本地进程（每次都要加载模型，很慢）
MINERU_REMOTE_URL = _env("MINERU_REMOTE_URL", "http://127.0.0.1:8100")
MINERU_TIER = _env("MINERU_TIER", "advanced")   # advanced 会做图片理解，生成图注
MINERU_TIMEOUT = _env_int("MINERU_TIMEOUT", 900)

# ---------------------------------------------------------------- LLM (vLLM)
LLM_BASE_URL = _env("LLM_BASE_URL", "http://127.0.0.1:8001/v1")
LLM_MODEL = _env("LLM_MODEL", "qwen3.5-0.8b")   # 与启动时的 --served-model-name 一致
LLM_API_KEY = _env("LLM_API_KEY", "EMPTY")
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 180.0)
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 1024)
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.3)

# ---------------------------------------------------------------- 检索 / 多模态
TOP_K = _env_int("TOP_K", 8)                 # 召回条数（覆盖"五种范式"这类多主题问题）
MAX_CHUNK_CHARS = _env_int("MAX_CHUNK_CHARS", 600)   # 单块送进 prompt 的最大字数
MAX_IMAGES_TO_LLM = _env_int("MAX_IMAGES_TO_LLM", 3)  # 一次问答最多塞几张图给 VLM
IMAGE_MAX_SIDE = _env_int("IMAGE_MAX_SIDE", 896)      # 送模型前缩放，控制 token 与带宽
EVIDENCE_INLINE_LIMIT = _env_int("EVIDENCE_INLINE_LIMIT", 4)  # 正文里内联展示的证据条数

# ---------------------------------------------------------------- Web
HOST = _env("HOST", "0.0.0.0")
PORT = _env_int("PORT", 8080)
PUBLIC_BASE = _env("PUBLIC_BASE", "")   # 对外访问前缀，前端拼图片 URL 时用（留空=同源）
