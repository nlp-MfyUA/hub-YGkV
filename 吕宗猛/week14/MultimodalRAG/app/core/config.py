"""Application settings loaded from environment variables."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MultimodalRAG"
    app_debug: bool = False
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    data_dir: str = str(PROJECT_ROOT / "data")
    max_upload_mb: int = 100

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "rag_mm"
    mysql_password: str = ""
    mysql_database: str = "rag_mm"
    mysql_connect_timeout: int = 10

    kafka_enabled: bool = True
    kafka_bootstrap_servers: str = "127.0.0.1:9092"
    kafka_topic: str = "mm.pdf.parse"
    kafka_group: str = "mm-rag-worker"
    kafka_client_id: str = "mm-rag"

    mineru_url: str = "http://127.0.0.1:8003"
    mineru_tier: str = "basic"
    mineru_timeout: int = 1800
    mineru_mock: bool = False

    model_service_url: str = "http://127.0.0.1:8901"
    model_service_api_key: str = ""
    embedding_model: str = "bge-small-zh-v1.5"
    embedding_batch_size: int = 32

    magpie_base_url: str = "http://127.0.0.1:3425/v1"
    magpie_api_key: str = ""
    magpie_model: str = "workbuddy/deepseek-v4.1-flash"
    llm_timeout: int = 180
    llm_max_tokens: int = 2048

    chat_top_k: int = 6
    chat_context_max_chunks: int = 8
    chat_history_messages: int = 8
    chat_max_images: int = 8

    sse_poll_seconds: float = 1.0
    sse_heartbeat_seconds: float = 15.0

    @property
    def upload_dir(self) -> Path:
        return Path(self.data_dir) / "uploads"

    @property
    def parsed_dir(self) -> Path:
        return Path(self.data_dir) / "parsed"

    @property
    def chat_upload_dir(self) -> Path:
        return Path(self.data_dir) / "chat_uploads"

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    def ensure_dirs(self) -> None:
        for path in (self.upload_dir, self.parsed_dir, self.chat_upload_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
