"""Environment and port configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_local_env() -> None:
    """Load key=value pairs from homework1/.env without overriding existing env vars."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ and value:
            os.environ[key] = value


@dataclass(frozen=True)
class LLMSettings:
    """Resolved LLM connection settings."""

    mode: str  # "openai" or "mock"
    api_key: str
    base_url: str
    model: str


def get_llm_settings() -> LLMSettings:
    """Resolve LLM mode (`openai` vs `mock`) and connection parameters."""
    load_local_env()
    requested = os.getenv("LLM_MODE", "mock").strip().lower()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    if requested not in {"auto", "openai", "mock"}:
        raise RuntimeError("LLM_MODE must be auto, openai, or mock.")

    if requested == "mock":
        mode = "mock"
    elif requested == "openai":
        if not api_key:
            raise RuntimeError("LLM_MODE=openai requires OPENAI_API_KEY to be set.")
        mode = "openai"
    else:
        mode = "openai" if api_key else "mock"

    return LLMSettings(mode=mode, api_key=api_key, base_url=base_url, model=model)
