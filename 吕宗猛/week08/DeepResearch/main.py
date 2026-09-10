"""服务入口：建表、种子账号、加载 .env、挂载静态目录后启动 uvicorn。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


def load_env():
    """轻量 .env 加载（避免多引 python-dotenv 依赖）：KEY=VALUE，# 注释。"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env()
    import db
    import auth
    db.init_db()
    auth.seed_admin()

    import uvicorn
    from api import app
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
