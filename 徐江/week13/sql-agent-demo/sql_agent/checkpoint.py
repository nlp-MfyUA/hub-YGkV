"""LangGraph checkpointer 工厂（week13 新增）。

LangGraph 的「状态」之所以可回放、可回查、可跨重启恢复，靠的就是
checkpointer：每个节点执行后把 state 快照序列化存起来。本模块按配置
（``graph.checkpoint``）创建对应的 saver：

- ``memory``：:class:`MemorySaver`，进程内存储（默认，零依赖）；
- ``sqlite``：:class:`SqliteSaver`，落库存储，重启后仍可回查
  （需 ``pip install langgraph-checkpoint-sqlite``；缺失时自动降级为 memory）。

另外解决一个序列化细节：我们的 state 里带有 StageTrace / DatabaseSchema 等
自定义 dataclass，langgraph 默认的 msgpack 序列化器会打印
「Deserializing unregistered type ...」警告（未来版本将直接拒绝）。
这里用 :class:`JsonPlusSerializer` 显式登记这些类型，序列化/反序列化都干净。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from .config import Config
from .db import ColumnInfo, DatabaseSchema, ForeignKeyInfo, TableInfo
from .models import ExecutionResult, LLMUsage, StageTrace

# state 中会落进 checkpoint 的自定义类型（登记进 msgpack 白名单）
_STATE_TYPES = (
    StageTrace, LLMUsage, ExecutionResult,
    DatabaseSchema, TableInfo, ColumnInfo, ForeignKeyInfo,
)


def state_serde() -> JsonPlusSerializer:
    """带自定义类型白名单的序列化器（memory / sqlite 两种 saver 共用）。"""
    return JsonPlusSerializer(allowed_msgpack_modules=_STATE_TYPES)


def create_memory_checkpointer() -> MemorySaver:
    return MemorySaver(serde=state_serde())


def create_checkpointer(config: Config) -> BaseCheckpointSaver:
    """按配置创建 checkpointer；sqlite 不可用时降级为 memory 并说明原因。"""
    if config.graph.checkpoint == "sqlite":
        conn = _open_sqlite(config.graph.checkpoint_path)
        if conn is not None:
            from langgraph.checkpoint.sqlite import SqliteSaver

            # check_same_thread=False：FastAPI 同步端点在线程池执行，
            # 同一连接可能被多个线程使用；演示项目可接受。
            return SqliteSaver(conn, serde=state_serde())
        print("[graph] sqlite checkpoint 不可用，已降级为 memory")
    return create_memory_checkpointer()


def _open_sqlite(path: str) -> sqlite3.Connection | None:
    """打开（必要时创建）sqlite checkpoint 库连接；依赖缺失返回 None。"""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401
    except ImportError:
        print("[graph] 未安装 langgraph-checkpoint-sqlite，"
              "memory checkpoint 已够用；如需落库请 pip install langgraph-checkpoint-sqlite")
        return None
    p = Path(path)
    if not p.is_absolute():
        # 相对路径相对项目根目录（与 db.path 的解析方式一致）
        # checkpoint.py 位于 <项目根>/sql_agent/ 下，parents[1] 即项目根
        p = Path(__file__).resolve().parents[1] / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(p), check_same_thread=False)


__all__ = ["create_checkpointer", "create_memory_checkpointer", "state_serde"]
