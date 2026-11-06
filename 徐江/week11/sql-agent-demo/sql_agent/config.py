"""配置加载。

优先级：环境变量 > 配置文件（默认 config.local.yaml）> 内置默认值。
首次运行时会从 config.example.yaml 自动复制一份 config.local.yaml。
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_FILE = "config.local.yaml"
EXAMPLE_CONFIG_FILE = "config.example.yaml"

PROVIDERS = ("deepseek", "mock")


class ConfigError(RuntimeError):
    """配置错误。"""


@dataclass
class LLMConfig:
    provider: str = "deepseek"                 # deepseek | mock（mock 为离线模拟，无需 Key）
    base_url: str = "https://api.deepseek.com"  # OpenAI 兼容接口地址
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
    net_max_retries: int = 2                   # 网络层重试次数（不含首次调用）


@dataclass
class DBConfig:
    path: str = "data/ecommerce.db"


@dataclass
class EvalConfig:
    max_attempts: int = 3                      # 工作流重试上限：生成 + 改写的总尝试次数
    row_limit: int = 100                       # 执行阶段最多返回的行数
    query_timeout_seconds: float = 10.0        # 单条 SQL 执行超时（秒）
    summarize: bool = True                     # 是否调用 LLM 做结果汇总


@dataclass
class Config:
    llm: LLMConfig
    db: DBConfig
    eval: EvalConfig
    source: str = ""

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        if path is None:
            path = DEFAULT_CONFIG_FILE
            if not Path(path).exists() and Path(EXAMPLE_CONFIG_FILE).exists():
                shutil.copyfile(EXAMPLE_CONFIG_FILE, DEFAULT_CONFIG_FILE)
                print(f"[config] 已从 {EXAMPLE_CONFIG_FILE} 复制生成 {DEFAULT_CONFIG_FILE}，"
                      f"请编辑该文件填入 API Key")
        p = Path(path)
        if not p.exists():
            raise ConfigError(
                f"配置文件不存在: {p.resolve()}\n"
                f"请从 config.example.yaml 复制一份并修改。"
            )
        data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

        def _section(name: str, model: type) -> Any:
            raw = data.get(name) or {}
            fields = {f for f in model.__dataclass_fields__}  # type: ignore[attr-defined]
            unknown = set(raw) - fields
            if unknown:
                print(f"[config] 警告: {name} 下存在未知配置项 {sorted(unknown)}，已忽略")
            return model(**{k: v for k, v in raw.items() if k in fields})

        cfg = cls(
            llm=_section("llm", LLMConfig),
            db=_section("db", DBConfig),
            eval=_section("eval", EvalConfig),
            source=str(p),
        )
        cfg._apply_env_overrides()
        cfg.validate()
        return cfg

    def _apply_env_overrides(self) -> None:
        """环境变量覆盖，便于 CI / 临时切换，不写入配置文件。"""
        mapping = {
            "LLM_PROVIDER": ("provider", str),
            "LLM_API_KEY": ("api_key", str),
            "LLM_BASE_URL": ("base_url", str),
            "LLM_MODEL": ("model", str),
        }
        for env, (attr, cast) in mapping.items():
            value = os.environ.get(env)
            if value:
                setattr(self.llm, attr, cast(value))

    # --------------------------------------------------------------- validate
    def validate(self) -> None:
        if self.llm.provider not in PROVIDERS:
            raise ConfigError(
                f"不支持的 llm.provider: {self.llm.provider!r}，可选: {list(PROVIDERS)}"
            )
        if self.eval.max_attempts < 1:
            raise ConfigError("eval.max_attempts 必须 >= 1")
        if self.eval.row_limit < 1:
            raise ConfigError("eval.row_limit 必须 >= 1")
