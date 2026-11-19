import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("RAG_DATA_DIR", str(ROOT / "data"))).resolve()
DOCUMENTS = DATA / "documents"
DATABASE = DATA / "rag.sqlite3"
BROKER = os.getenv("KAFKA_BOOTSTRAP_SERVERS", f"127.0.0.1:{os.getenv('KAFKA_PORT', '19092')}")
TOPIC = os.getenv("KAFKA_RAG_TOPIC", "wk14-rag-pdf-v1")
GROUP = os.getenv("KAFKA_RAG_GROUP", "wk14-rag-mineru-v1")
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BATCH = 10
MINERU_TIER = os.getenv("MINERU_TIER", "flash")
MINERU_TIMEOUT = int(os.getenv("MINERU_TIMEOUT", "1800"))
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
