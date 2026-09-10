import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    output_dir: Path = Path("outputs")

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "").strip(),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
            output_dir=Path(os.environ.get("RESEARCH_OUTPUT_DIR", "outputs")),
        )

    def configuration_errors(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("缺少 DEEPSEEK_API_KEY 环境变量")
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            errors.append("DEEPSEEK_BASE_URL 必须为不含凭据、查询参数的 HTTPS 接口地址")
        if not self.model:
            errors.append("DEEPSEEK_MODEL 不能为空")
        return errors
