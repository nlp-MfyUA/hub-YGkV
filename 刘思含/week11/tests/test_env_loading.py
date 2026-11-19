"""Tests for environment template and .gitignore hygiene."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
GITIGNORE = ROOT / ".gitignore"


def _merged_env_vars() -> list[str]:
    """Return environment variable names where merged via os.environ.get."""
    names: set[str] = set()
    for base in ("app", "pipeline"):
        for path in (ROOT / base).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            names.update(re.findall(r'os\.environ\.get\(\s*"([A-Z_]+)"', text))
    return sorted(names)


def _keys_in_env_example() -> set[str]:
    """Return variable names declared in .env.example (including comments)."""
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", content, re.MULTILINE))


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file()


def test_env_example_matches_code_reads() -> None:
    """Every env var read by code is documented; no undocumented extras."""
    documented = _keys_in_env_example()
    # OPENAI_* are read by the openai SDK, not by this codebase.
    documented -= {"OPENAI_API_KEY", "OPENAI_BASE_URL"}
    code_reads = set(_merged_env_vars())
    assert code_reads <= documented, code_reads - documented
    # The template must not document variables that no code reads.
    extra = documented - code_reads
    assert extra == set(), extra


def test_env_example_has_required_keys() -> None:
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" in content
    assert "DEEPSEEK_API_KEY" in content
    assert "DEEPSEEK_BASE_URL" in content
    assert "DEEPSEEK_MODEL=deepseek-flash" in content
    assert "VULN_DB_PATH" in content
    assert "CHART_OUTPUT_ROOT" in content
    assert "MODEL_NAME" in content
    assert "SESSION_DIR" in content
    assert "LOG_LEVEL" in content


def test_env_example_uses_placeholder_key() -> None:
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-your-key-here" in content


def test_gitignore_excludes_env() -> None:
    lines = {
        line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
    }
    assert ".env" in lines
    assert ".env.local" in lines


def test_gitignore_excludes_generated_databases() -> None:
    content = GITIGNORE.read_text(encoding="utf-8")
    assert "*.db" in content
    assert "data/chat_history_*.db" in content
    assert "app/db/vuln_test_agent.db" in content
    assert "data/charts/" in content


def test_dotenv_is_loaded_by_main() -> None:
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "from dotenv import load_dotenv" in source
    assert "load_dotenv()" in source


def test_env_file_is_not_committed_artifact() -> None:
    """If .env exists locally it must use an empty key placeholder."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    lines = env_file.read_text(encoding="utf-8").splitlines()
    key_lines = [line for line in lines if line.startswith("OPENAI_API_KEY=")]
    assert key_lines
    assert key_lines[0].strip() in (
        "OPENAI_API_KEY=",
        "OPENAI_API_KEY=sk-your-key-here",
    )
