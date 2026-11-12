"""作业1：用 Redis 存储多轮对话历史。

运行（先启动 compose.yml 中的 redis）：
    python redis_demo.py            # 默认连接 localhost:6379

要点：
- 每个会话一个 List，RPUSH 追加、LRANGE 读取，天然按时间排序；
- LTRIM 保留最近 N 轮，避免历史无限增长；
- EXPIRE 给会话加过期时间，闲置会话自动回收；
- 演示“带历史上下文”的提示词拼装，以及会话列表 TTL 查询。
"""
from __future__ import annotations

import json
import os
import time
import uuid

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
HISTORY_KEY = "chat:history:{session_id}"
INDEX_KEY = "chat:sessions"          # ZSET：按最后活跃时间排序的会话索引
MAX_TURNS = int(os.getenv("MAX_TURNS", "10"))   # 只保留最近 10 条消息
TTL_SECONDS = int(os.getenv("SESSION_TTL", "3600"))


class ChatMemory:
    def __init__(self, client: redis.Redis | None = None):
        self.r = client or redis.from_url(REDIS_URL, decode_responses=True)

    def new_session(self) -> str:
        return uuid.uuid4().hex[:12]

    def append(self, session_id: str, role: str, content: str) -> None:
        key = HISTORY_KEY.format(session_id=session_id)
        pipe = self.r.pipeline(transaction=True)
        pipe.rpush(key, json.dumps({"role": role, "content": content,
                                    "ts": int(time.time())}, ensure_ascii=False))
        pipe.ltrim(key, -MAX_TURNS, -1)
        pipe.expire(key, TTL_SECONDS)
        pipe.zadd(INDEX_KEY, {session_id: time.time()})
        pipe.execute()

    def messages(self, session_id: str) -> list[dict]:
        raw = self.r.lrange(HISTORY_KEY.format(session_id=session_id), 0, -1)
        return [json.loads(item) for item in raw]

    def build_prompt(self, session_id: str, question: str, limit: int = 6) -> list[dict]:
        """把历史消息拼成 OpenAI 兼容的 messages，供 LLM 调用。"""
        history = self.messages(session_id)[-limit:]
        system = {"role": "system", "content": "你是食堂采购问答助手，回答要简洁。"}
        return [system] + [{"role": m["role"], "content": m["content"]} for m in history] + \
               [{"role": "user", "content": question}]

    def active_sessions(self, top: int = 5) -> list[tuple[str, float, int]]:
        result = []
        for sid in self.r.zrevrange(INDEX_KEY, 0, top - 1):
            ttl = self.r.ttl(HISTORY_KEY.format(session_id=sid))
            size = self.r.llen(HISTORY_KEY.format(session_id=sid))
            result.append((sid, ttl, size))
        return result

    def clear(self, session_id: str) -> None:
        self.r.delete(HISTORY_KEY.format(session_id=session_id))
        self.r.zrem(INDEX_KEY, session_id)


def main() -> None:
    memory = ChatMemory()
    sid = memory.new_session()
    print(f"新会话：{sid}")
    rounds = [
        ("user", "我们食堂这周大米采购价是多少？"),
        ("assistant", "本周大米采购均价 2.35 元/斤。"),
        ("user", "比上周呢？"),
        ("assistant", "比上周下降 1.2%。"),
    ]
    for role, text in rounds:
        memory.append(sid, role, text)
    print("历史消息：")
    for m in memory.messages(sid):
        print(f"  [{m['role']}] {m['content']}")

    print("\n发给大模型的 messages：")
    for m in memory.build_prompt(sid, "食用油和上周比变化大吗？"):
        print(f"  {m['role']}: {m['content']}")

    print("\n活跃会话（会话号, 剩余过期秒数, 消息条数）：", memory.active_sessions())
    memory.clear(sid)


if __name__ == "__main__":
    main()
