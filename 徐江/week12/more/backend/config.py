"""配置层：从 .env 读取全部运行参数（pydantic-settings）。

设计原则（见技术设计文档 §11）：
- 所有密钥、base_url、模型名只来自环境变量，代码不写死任何端点；
- 本模块只做"读取 + 默认值"，缺失校验放在 main.py 的 lifespan 启动钩子里，
  以便给出中文可读的启动失败原因。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Provider 选择：deepseek | qwen ----
    vision_provider: str = Field(default="deepseek", alias="VISION_PROVIDER")

    # ---- DeepSeek（主通道；base_url 按服务商文档填写） ----
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-v4.1-flash", alias="DEEPSEEK_MODEL")

    # ---- Qwen（备选通道，DashScope compatible-mode） ----
    qwen_api_key: str = Field(default="", alias="QWEN_API_KEY")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL",
    )
    qwen_model: str = Field(default="qwen-vl-max", alias="QWEN_MODEL")

    # ---- 通用 ----
    max_image_mb: int = Field(default=8, alias="MAX_IMAGE_MB")
    min_image_side: int = Field(default=224, alias="MIN_IMAGE_SIDE")
    timeout_s: float = Field(default=30.0, alias="TIMEOUT_S")
    max_retries: int = Field(default=1, alias="MAX_RETRIES")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    demo_token: str = Field(default="", alias="DEMO_TOKEN")

    # ---- 派生：当前生效通道的密钥 / base_url / 模型 ----
    @property
    def active_api_key(self) -> str:
        return self.deepseek_api_key if self.vision_provider == "deepseek" else self.qwen_api_key

    @property
    def active_base_url(self) -> str:
        return self.deepseek_base_url if self.vision_provider == "deepseek" else self.qwen_base_url

    @property
    def active_model(self) -> str:
        return self.deepseek_model if self.vision_provider == "deepseek" else self.qwen_model


@lru_cache
def get_settings() -> Settings:
    """进程内单例；uvicorn 启动时读取一次，测试可 clear 缓存后重建。"""
    return Settings()
