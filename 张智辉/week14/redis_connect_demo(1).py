"""
Redis 连接示例（本机 Docker 环境）
运行：python3 redis_connect_demo.py
"""
import redis
import json

# ---------- 1. 最简连接 ----------
r = redis.Redis(
    host="127.0.0.1",
    port=6379,
    db=0,
    password=None,          # 没设密码就写 None
    decode_responses=True,  # 返回 str 而不是 bytes
    socket_timeout=3,       # 超时，别让它卡死
    socket_connect_timeout=3,
)

print("PING ->", r.ping())


# ---------- 2. 连接池（生产必用）----------
pool = redis.ConnectionPool(
    host="127.0.0.1", port=6379, db=0,
    max_connections=50,
    decode_responses=True,
)
r = redis.Redis(connection_pool=pool)


# ---------- 3. 基本读写 ----------
r.set("demo:name", "小明", ex=60)          # 60 秒过期
print("GET ->", r.get("demo:name"))
print("TTL ->", r.ttl("demo:name"), "秒")

r.hset("demo:user:1", mapping={"name": "小明", "age": 18, "city": "北京"})
print("HGETALL ->", r.hgetall("demo:user:1"))

r.zadd("demo:rank", {"张三": 100, "李四": 92, "王五": 88})
print("排行榜 ->", r.zrevrange("demo:rank", 0, 2, withscores=True))

r.lpush("demo:queue", "job1", "job2")
print("队列 ->", r.lrange("demo:queue", 0, -1))

r.sadd("demo:tags", "redis", "docker")
print("集合 ->", r.smembers("demo:tags"))


# ---------- 4. Pipeline 批量 ----------
pipe = r.pipeline(transaction=False)       # False: 不包 MULTI，纯批量
for i in range(5):
    pipe.incr("demo:counter")
print("Pipeline ->", pipe.execute())


# ---------- 5. Lua 脚本（原子操作）----------
lua = """
local cur = redis.call('INCR', KEYS[1])
if cur == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return cur
"""
print("Lua 限流计数 ->", r.eval(lua, 1, "demo:rate", 60))


# ---------- 6. 存对象（JSON 序列化）----------
user = {"id": 1, "name": "小明", "tags": ["vip", "new"]}
r.set("demo:json", json.dumps(user, ensure_ascii=False))
print("对象 ->", json.loads(r.get("demo:json")))


# ---------- 7. 清理 ----------
keys = r.keys("demo:*")
if keys:
    r.delete(*keys)
print(f"已清理 {len(keys)} 个演示 key")


# ---------- 8. 常见错误处理 ----------
from redis.exceptions import ConnectionError, TimeoutError, AuthenticationError

try:
    r.ping()
except (ConnectionError, TimeoutError) as e:
    print("连不上 Redis：", e)
except AuthenticationError:
    print("密码错误")
finally:
    pool.disconnect()
