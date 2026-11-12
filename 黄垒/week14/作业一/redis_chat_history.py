#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis 实践 1/2：用 Redis 存储多轮对话历史
=============================================

场景：大模型对话服务需要保存每个用户的会话历史，要求：
  1) 消息按时间有序、可追加、可只取最近 N 条（上下文窗口有上限）
  2) 能列出某用户的所有会话，按最后活跃时间倒序
  3) 冷会话自动过期，不无限占用内存

Key 设计（统一 chat: 前缀，便于 SCAN / 统计）
  chat:msgs:{sid}              LIST    消息流，RPUSH 追加，每条是 JSON
  chat:meta:{sid}              HASH    会话元信息 title/model/created_at/updated_at/msg_count
  chat:user:{uid}:sessions     ZSET    sid -> 最后活跃时间戳（会话列表按时间排序）
  chat:user:{uid}:active       STRING  当前活跃会话 id

为什么这样选类型：
  LIST  -> 天然有序；RPUSH 追加是 O(1)；LRANGE -N -1 取最近 N 条；
           LTRIM 保留尾部 N 条，天然实现"只留最近 N 轮"的滑动窗口
  HASH  -> 元信息按字段读写，改一个字段不用重写整块 JSON
  ZSET  -> score 存时间戳，ZREVRANGE 取最近会话 O(logN)
  TTL   -> 每个会话独立过期，读的时候不刷新，写的时候刷新（活跃才续期）

用法：
  python3 redis_chat_history.py demo            # 一键演示
  python3 redis_chat_history.py add  --user u1 --session s1 --role user --content "你好"
  python3 redis_chat_history.py show --session s1
  python3 redis_chat_history.py list --user u1
  python3 redis_chat_history.py clear --session s1
"""

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional

import redis

# ------------------------------------------------------------------ 配置
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
KEY_PREFIX = "chat:"

MAX_MSGS_PER_SESSION = 200          # 单会话最多保留的消息条数（LTRIM 滑动窗口）
SESSION_TTL = 7 * 24 * 3600         # 会话 7 天不活跃则自动过期

K_MSGS = KEY_PREFIX + "msgs:{sid}"
K_META = KEY_PREFIX + "meta:{sid}"
K_USER_SESSIONS = KEY_PREFIX + "user:{uid}:sessions"
K_ACTIVE = KEY_PREFIX + "user:{uid}:active"


# ------------------------------------------------------------------ 核心封装
class ChatHistoryStore:
    """把所有 key 的读写收敛到一个类里，业务侧只关心"追加一条消息/取最近 N 条"。"""

    def __init__(self, host: str = REDIS_HOST, port: int = REDIS_PORT, db: int = REDIS_DB,
                 max_msgs: int = MAX_MSGS_PER_SESSION, ttl: int = SESSION_TTL):
        self.r = redis.Redis(
            host=host, port=port, db=db,
            decode_responses=True,     # 直接拿 str，省掉到处 .decode()
            socket_timeout=5,
            socket_connect_timeout=5,
            health_check_interval=30,
        )
        self.r.ping()                  # 启动即探活，配错地址立刻失败
        self.max_msgs = max_msgs
        self.ttl = ttl

    # ---------------- 写 ----------------
    def append(self, user_id: str, session_id: str, role: str, content: str,
               model: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """追加一条消息。

        用 pipeline 把 9 条命令打成一次往返，避免"写消息 + 更新计数 + 更新索引"
        分三次 RTT。transaction=True 保证这一批命令原子执行（MULTI/EXEC）。
        """
        now = time.time()
        msg: Dict[str, Any] = {"role": role, "content": content, "ts": now}
        if extra:
            msg.update(extra)

        k_msgs = K_MSGS.format(sid=session_id)
        k_meta = K_META.format(sid=session_id)
        k_sessions = K_USER_SESSIONS.format(uid=user_id)
        k_active = K_ACTIVE.format(uid=user_id)

        pipe = self.r.pipeline(transaction=True)
        # 1) 追加消息 + 裁掉超出窗口的旧消息
        pipe.rpush(k_msgs, json.dumps(msg, ensure_ascii=False))
        pipe.ltrim(k_msgs, -self.max_msgs, -1)
        # 2) 元信息：用 HINCRBY 自增计数，避免"读-改-写"竞态
        pipe.hset(k_meta, mapping={
            "session_id": session_id,
            "user_id": user_id,
            "model": model or "default",
        })
        pipe.hsetnx(k_meta, "title", content[:30])        # 首条消息做标题
        pipe.hsetnx(k_meta, "created_at", now)
        pipe.hset(k_meta, "updated_at", now)
        pipe.hincrby(k_meta, "msg_count", 1)
        # 3) 会话索引 + 活跃会话指针
        pipe.zadd(k_sessions, {session_id: now})
        pipe.set(k_active, session_id)
        # 4) 每次写都续期，读不续期 —— 只有活跃会话才活着
        pipe.expire(k_msgs, self.ttl)
        pipe.expire(k_meta, self.ttl)
        pipe.expire(k_sessions, self.ttl)
        pipe.expire(k_active, self.ttl)
        pipe.execute()

        msg["_index"] = self.r.llen(k_msgs) - 1           # 该消息在 LIST 中的下标
        return msg

    # ---------------- 读 ----------------
    def history(self, session_id: str, limit: int = 20, newest_first: bool = False) -> List[Dict[str, Any]]:
        """取最近 limit 条消息（按时间正序，可直接拼成 LLM 的 messages）。

        LRANGE -limit -1：只读尾部，不关心前面有多少条，O(limit)。
        """
        raw = self.r.lrange(K_MSGS.format(sid=session_id), -limit, -1)
        msgs = [json.loads(x) for x in raw]
        return list(reversed(msgs)) if newest_first else msgs

    def page(self, session_id: str, page: int = 1, size: int = 10) -> List[Dict[str, Any]]:
        """分页读取（page 从 1 开始，按时间正序）。"""
        start = (page - 1) * size
        raw = self.r.lrange(K_MSGS.format(sid=session_id), start, start + size - 1)
        return [json.loads(x) for x in raw]

    def meta(self, session_id: str) -> Dict[str, Any]:
        m = self.r.hgetall(K_META.format(sid=session_id))
        if m:
            m["ttl"] = self.r.ttl(K_META.format(sid=session_id))
            m["msg_count"] = int(m.get("msg_count", 0))
        return m

    def list_sessions(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """按最后活跃时间倒序列出会话：先 ZREVRANGE 拿 id，再 pipeline 批量取 meta。"""
        pairs = self.r.zrevrange(K_USER_SESSIONS.format(uid=user_id), 0, limit - 1, withscores=True)
        if not pairs:
            return []
        pipe = self.r.pipeline(transaction=False)
        for sid, _ in pairs:
            pipe.hgetall(K_META.format(sid=sid))
        metas = pipe.execute()
        out = []
        for (sid, score), m in zip(pairs, metas):
            out.append({
                "session_id": sid,
                "title": m.get("title", ""),
                "msg_count": int(m.get("msg_count", 0)),
                "last_active": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(score)),
            })
        return out

    def active_session(self, user_id: str) -> Optional[str]:
        return self.r.get(K_ACTIVE.format(uid=user_id))

    # ---------------- 删 ----------------
    def clear(self, user_id: str, session_id: str) -> int:
        """删除一个会话；返回删掉的 key 个数。"""
        pipe = self.r.pipeline(transaction=True)
        pipe.delete(K_MSGS.format(sid=session_id), K_META.format(sid=session_id))
        pipe.zrem(K_USER_SESSIONS.format(uid=user_id), session_id)
        res = pipe.execute()
        return int(res[0])

    def stats(self) -> Dict[str, Any]:
        """统计当前库里的会话规模。用 SCAN 而不是 KEYS —— KEYS 会阻塞 Redis。"""
        info = self.r.info("memory")
        sessions = set()
        n_keys = 0
        for k in self.r.scan_iter(match=KEY_PREFIX + "msgs:*", count=200):
            sessions.add(k.rsplit(":", 1)[-1])
            n_keys += 1
        return {
            "dbsize": self.r.dbsize(),
            "scan_msgs_keys": n_keys,
            "sessions": sorted(sessions),
            "used_memory_human": info.get("used_memory_human"),
        }


# ------------------------------------------------------------------ 演示
def _print_msgs(msgs: List[Dict[str, Any]], title: str = ""):
    if title:
        print(f"  {title}")
    for i, m in enumerate(msgs):
        ts = time.strftime("%H:%M:%S", time.localtime(m["ts"]))
        print(f"    [{ts}] {m['role']:<9} | {m['content']}")


def cmd_demo(store: ChatHistoryStore):
    uid = "user_1001"
    print("=" * 72)
    print("Redis 对话历史演示")
    print("=" * 72)

    # 造两个会话：s_alpha（问答）、s_beta（下单咨询）
    conv_a = [
        ("user", "帮我看看 600519 今天的走势"),
        ("assistant", "600519 现价 1685.20，涨幅 +1.32%，成交额 42.6 亿，主力净流入 1.8 亿。"),
        ("user", "那和 000858 比呢"),
        ("assistant", "000858 现价 142.30，涨幅 +0.85%；600519 涨幅更强，但 000858 估值更低。"),
    ]
    conv_b = [
        ("user", "我的持仓怎么设置止盈"),
        ("assistant", "建议按成本价 +15% 分批止盈，回撤 5% 触发移动止损。"),
    ]

    for s in ("s_alpha", "s_beta"):
        store.clear(uid, s)

    for role, content in conv_a:
        store.append(uid, "s_alpha", role, content, model="qwen3.5-0.8b")
    for role, content in conv_b:
        store.append(uid, "s_beta", role, content, model="qwen3.5-0.8b")

    print("\n[1] 会话列表（ZSET 按最后活跃时间倒序）")
    for i, s in enumerate(store.list_sessions(uid), 1):
        print(f"  {i}. {s['session_id']:<10} 标题={s['title'][:18]:<20} "
              f"消息数={s['msg_count']:<3} 最后活跃={s['last_active']}")

    print("\n[2] 当前活跃会话（STRING 指针）: "
          f"{store.active_session(uid)}")

    print(f"\n[3] s_alpha 最近 3 条（LRANGE -3 -1，可直接拼给 LLM）")
    _print_msgs(store.history("s_alpha", limit=3), "正序：")
    _print_msgs(store.history("s_alpha", limit=3, newest_first=True), "倒序：")

    print("\n[4] s_alpha 第 1 页（每页 2 条，LRANGE 下标计算）")
    _print_msgs(store.page("s_alpha", page=1, size=2))

    print("\n[5] 元信息（HASH） + TTL")
    for k, v in store.meta("s_alpha").items():
        print(f"    {k:<12} = {v}")

    print("\n[6] 原始命令回放 —— Redis 里到底存了什么")
    print(f"    TYPE chat:msgs:s_alpha   -> {store.r.type('chat:msgs:s_alpha')}")
    print(f"    LLEN chat:msgs:s_alpha   -> {store.r.llen('chat:msgs:s_alpha')}")
    print(f"    HGETALL chat:meta:s_alpha-> {store.r.hgetall('chat:meta:s_alpha')}")
    print(f"    ZRANGE ...:sessions 0 -1 WITHSCORES")
    for sid, score in store.r.zrange(K_USER_SESSIONS.format(uid=uid), 0, -1, withscores=True):
        print(f"        {sid} -> {score}")

    print("\n[7] 库统计（SCAN 遍历，不阻塞主线程）")
    st = store.stats()
    print(f"    dbsize={st['dbsize']}  会话={st['sessions']}  "
          f"used_memory={st['used_memory_human']}")

    print("\n[8] 清理演示数据")
    print(f"    删除 s_beta -> 删掉 {store.clear(uid, 's_beta')} 个 key；"
          f"剩余会话={store.list_sessions(uid)[0]['session_id']}")
    print("\n演示结束。数据保留在 Redis 中，可继续用 show/list 子命令查看。")


# ------------------------------------------------------------------ CLI
def build_store(args) -> ChatHistoryStore:
    return ChatHistoryStore(host=args.host, port=args.port, db=args.db)


def main():
    p = argparse.ArgumentParser(description="Redis 对话历史存储实践")
    p.add_argument("--host", default=REDIS_HOST)
    p.add_argument("--port", type=int, default=REDIS_PORT)
    p.add_argument("--db", type=int, default=REDIS_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("demo", help="一键演示")

    a = sub.add_parser("add", help="追加一条消息")
    a.add_argument("--user", required=True)
    a.add_argument("--session", required=True)
    a.add_argument("--role", default="user", choices=["user", "assistant", "system"])
    a.add_argument("--content", required=True)

    s = sub.add_parser("show", help="查看会话消息")
    s.add_argument("--session", required=True)
    s.add_argument("--limit", type=int, default=20)

    l = sub.add_parser("list", help="列出用户会话")
    l.add_argument("--user", required=True)

    c = sub.add_parser("clear", help="删除会话")
    c.add_argument("--user", required=True)
    c.add_argument("--session", required=True)

    args = p.parse_args()

    try:
        store = build_store(args)
    except redis.exceptions.RedisError as e:
        print(f"连接 Redis 失败: {e}", file=sys.stderr)
        return 1

    if args.cmd == "demo":
        cmd_demo(store)
    elif args.cmd == "add":
        m = store.append(args.user, args.session, args.role, args.content)
        print(f"已写入 index={m['_index']}  {m['role']}: {m['content']}")
    elif args.cmd == "show":
        _print_msgs(store.history(args.session, limit=args.limit))
    elif args.cmd == "list":
        for s in store.list_sessions(args.user):
            print(f"{s['session_id']:<12} {s['msg_count']:<4} {s['last_active']}  {s['title']}")
    elif args.cmd == "clear":
        print(f"删除 {args.session}，共 {store.clear(args.user, args.session)} 个 key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
