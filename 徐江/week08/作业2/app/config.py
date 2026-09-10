"""
配置加载模块

支持从外部配置文件和环境变量加载配置
"""

import os
from pathlib import Path
from typing import Optional, Any, Dict
import yaml
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用配置类"""

    # Server 配置
    server_host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    server_port: int = Field(default=8000, alias="SERVER_PORT")
    server_reload: bool = Field(default=False, alias="SERVER_RELOAD")

    # API 配置
    bocha_api_key: str = Field(default="", alias="BOCHA_API_KEY")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")

    # LLM 配置
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4000

    # Embedding 配置
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # 搜索配置
    search_count: int = 10
    search_freshness: str = "oneYear"
    search_max_iterations: int = 3
    rerank_threshold: float = 0.7
    similarity_threshold: float = 0.6

    # 报告配置
    output_dir: str = "data/research"
    data_dir: str = "data"

    # 日志配置
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def load_yaml_config(config_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """从 YAML 文件加载配置"""
    path = Path(config_path)
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}