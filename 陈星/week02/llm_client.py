"""共享配置与 DeepSeek 客户端（OpenAI 兼容接口）"""
import os
from openai import OpenAI
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

load_dotenv(ENV_PATH, override=False)


def get_config():
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        "model": os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
    }


def save_config(api_key: str, base_url: str, model: str):
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(f"DEEPSEEK_API_KEY={api_key}\n")
        f.write(f"DEEPSEEK_BASE_URL={base_url}\n")
        f.write(f"DEEPSEEK_MODEL={model}\n")
    load_dotenv(ENV_PATH, override=True)
    os.environ["DEEPSEEK_API_KEY"] = api_key
    os.environ["DEEPSEEK_BASE_URL"] = base_url
    os.environ["DEEPSEEK_MODEL"] = model


def get_client(api_key=None, base_url=None):
    cfg = get_config()
    api_key = api_key or cfg["api_key"]
    base_url = base_url or cfg["base_url"]
    return OpenAI(api_key=api_key, base_url=base_url)


def chat(messages, model=None, api_key=None, base_url=None, stream=False, temperature=0.7):
    cfg = get_config()
    model = model or cfg["model"]
    client = get_client(api_key, base_url)
    return client.chat.completions.create(
        model=model,
        messages=messages,
        stream=stream,
        temperature=temperature,
    )
