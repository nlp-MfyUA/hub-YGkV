"""用 Redis List 保存对话历史。依赖：python -m pip install redis。"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from redis import Redis
from redis.exceptions import RedisError


def main() -> int:
    parser = argparse.ArgumentParser(description="按会话追加和读取 Redis 对话历史")
    parser.add_argument(
        "--url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:16379/0"),
        help="Redis 连接地址，可通过 REDIS_URL 设置",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="追加一条对话")
    add.add_argument("session", help="会话 ID")
    add.add_argument("role", choices=("user", "assistant", "system"))
    add.add_argument("content", help="对话内容")

    history = commands.add_parser("history", help="读取最近的对话")
    history.add_argument("session", help="会话 ID")
    history.add_argument("--limit", type=int, default=10, help="最多读取的条数，默认 10")

    args = parser.parse_args()
    if args.command == "history" and args.limit < 1:
        history.error("--limit 必须大于 0")

    key = f"chat:history:{args.session}"
    try:
        with Redis.from_url(
            args.url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3
        ) as client:
            if args.command == "add":
                record = {
                    "role": args.role,
                    "content": args.content,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                size = client.rpush(key, json.dumps(record, ensure_ascii=False))
                print(f"已追加到 {key}，共 {size} 条")
            else:
                # 负索引从列表末尾计数，结果仍按写入顺序排列。
                records = [json.loads(item) for item in client.lrange(key, -args.limit, -1)]
                print(json.dumps(records, ensure_ascii=False, indent=2))
    except (RedisError, ValueError) as exc:
        print(f"Redis 操作失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
