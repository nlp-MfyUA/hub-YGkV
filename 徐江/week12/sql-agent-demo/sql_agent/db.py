"""SQLite 示例数据库：建库、灌入确定性种子数据、解析 schema。

- build_database(): 首次运行时创建 data/ecommerce.db 并写入确定性种子数据
  （同一份代码在任何机器上生成的数据完全一致，保证 gold SQL 可比对）。
- parse_schema():   「数据库解析」阶段的核心：从 sqlite_master / PRAGMA 中抽取
  表、列、类型、主外键、行数、低基数列取值、样例行，构造 DatabaseSchema。
- connect_readonly(): 以只读模式（mode=ro）打开连接，防止任何写操作。
"""
from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# --------------------------------------------------------------------- DDL
DDL = """
CREATE TABLE users (
    user_id       INTEGER PRIMARY KEY,
    user_name     TEXT    NOT NULL,
    city          TEXT    NOT NULL,
    gender        TEXT,
    age           INTEGER,
    register_date TEXT    NOT NULL            -- 注册日期 YYYY-MM-DD
);

CREATE TABLE products (
    product_id   INTEGER PRIMARY KEY,
    product_name TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    price        REAL    NOT NULL,            -- 单价（元）
    stock        INTEGER NOT NULL             -- 库存（件）
);

CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    order_date   TEXT    NOT NULL,            -- 下单日期 YYYY-MM-DD
    status       TEXT    NOT NULL,            -- 订单状态
    total_amount REAL    NOT NULL             -- 订单总金额（元）
);

CREATE TABLE order_items (
    item_id    INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL,              -- 购买数量
    unit_price REAL    NOT NULL               -- 成交单价（元）
);
"""

TABLE_COMMENTS = {
    "users": "用户表",
    "products": "商品表",
    "orders": "订单表",
    "order_items": "订单明细表",
}

COLUMN_COMMENTS = {
    ("users", "user_id"): "用户ID",
    ("users", "user_name"): "用户姓名",
    ("users", "city"): "所在城市",
    ("users", "register_date"): "注册日期，YYYY-MM-DD",
    ("products", "product_id"): "商品ID",
    ("products", "product_name"): "商品名称",
    ("products", "category"): "商品品类",
    ("products", "price"): "单价（元）",
    ("products", "stock"): "库存（件）",
    ("orders", "order_id"): "订单ID",
    ("orders", "user_id"): "下单用户ID",
    ("orders", "order_date"): "下单日期，YYYY-MM-DD",
    ("orders", "status"): "订单状态",
    ("orders", "total_amount"): "订单总金额（元）",
    ("order_items", "item_id"): "明细ID",
    ("order_items", "order_id"): "所属订单ID",
    ("order_items", "product_id"): "商品ID",
    ("order_items", "quantity"): "购买数量",
    ("order_items", "unit_price"): "成交单价（元）",
}

# (product_id, name, category, price, stock) —— 固定 16 个商品，库存有高有低
PRODUCTS = [
    (1, "智能手机 Pro X1", "手机数码", 5299.00, 86),
    (2, "无线降噪耳机 Air", "手机数码", 799.00, 23),
    (3, "智能手表 S2", "手机数码", 1299.00, 45),
    (4, "4K 高清电视 55寸", "家用电器", 2999.00, 12),
    (5, "变频空调 1.5匹", "家用电器", 3199.00, 8),
    (6, "滚筒洗衣机 8kg", "家用电器", 1899.00, 15),
    (7, "电动牙刷 E3", "家用电器", 199.00, 120),
    (8, "男士休闲夹克", "服装鞋包", 399.00, 60),
    (9, "女士连衣裙", "服装鞋包", 299.00, 75),
    (10, "跑步鞋 Air Max", "服装鞋包", 559.00, 42),
    (11, "有机坚果礼盒", "食品饮料", 129.00, 200),
    (12, "进口牛奶 12盒", "食品饮料", 89.00, 150),
    (13, "手冲咖啡豆 500g", "食品饮料", 99.00, 90),
    (14, "Python 编程从入门到实践", "图书文具", 68.00, 110),
    (15, "真皮笔记本 A5", "图书文具", 45.00, 65),
    (16, "钢笔墨水套装", "图书文具", 79.00, 30),
]

USER_NAMES = [
    "张伟", "李娜", "王强", "刘洋", "陈静", "杨帆", "赵敏", "孙磊",
    "周琳", "吴军", "徐丽", "马超", "朱婷", "胡斌", "郭晶", "何欢",
    "高翔", "林悦", "郑宇", "宋佳",
]
CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安"]
ORDER_STATUSES = ["已完成", "已发货", "待发货", "已取消"]


# --------------------------------------------------------------- 建库与种子数据
def build_database(db_path: str | Path, *, rebuild: bool = False) -> Path:
    """创建示例数据库（已存在且不要求重建时直接返回）。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not rebuild:
        return path
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(DDL)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _seed(conn: sqlite3.Connection) -> None:
    """确定性种子数据：random.Random(20241021)，任何机器结果一致。

    刻意设计：
    - 20 个用户中只有前 15 个下过单，后 5 个从未下单（覆盖「未下单用户」类查询）；
    - 订单全部发生在 2024 年（覆盖年月聚合、下半年区间类查询）；
    - orders.total_amount 与其 order_items 的 quantity*unit_price 之和保持一致。
    """
    rng = random.Random(20241021)

    users = []
    for i in range(20):
        register = date(2023, 1, 1) + timedelta(days=rng.randint(0, 729))
        users.append((
            i + 1,
            USER_NAMES[i],
            CITIES[i % len(CITIES)],
            rng.choice(["男", "女"]),
            rng.randint(18, 60),
            register.isoformat(),
        ))
    conn.executemany("INSERT INTO users VALUES (?,?,?,?,?,?)", users)
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?)", PRODUCTS)

    order_id = 0
    item_id = 0
    for _ in range(80):
        order_id += 1
        user_id = rng.randint(1, 15)  # 用户 16~20 从未下单
        order_date = (date(2024, 1, 1) + timedelta(days=rng.randint(0, 364))).isoformat()
        status = rng.choices(ORDER_STATUSES, weights=[60, 15, 10, 15])[0]
        items = []
        total = 0.0
        for _ in range(rng.randint(1, 4)):
            item_id += 1
            product_id = rng.randint(1, 16)
            quantity = rng.randint(1, 5)
            unit_price = round(PRODUCTS[product_id - 1][3] * rng.uniform(0.92, 1.0), 2)
            total += quantity * unit_price
            items.append((item_id, order_id, product_id, quantity, unit_price))
        conn.execute(
            "INSERT INTO orders VALUES (?,?,?,?,?)",
            (order_id, user_id, order_date, status, round(total, 2)),
        )
        conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", items)


# ------------------------------------------------------------------ schema 解析
@dataclass
class ColumnInfo:
    name: str
    type: str
    not_null: bool
    primary_key: bool
    comment: str = ""
    distinct_values: list[str] = field(default_factory=list)


@dataclass
class ForeignKeyInfo:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableInfo:
    name: str
    comment: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKeyInfo]
    row_count: int
    ddl: str
    sample_rows: list[tuple]


@dataclass
class DatabaseSchema:
    tables: dict[str, TableInfo]

    @property
    def table_names(self) -> list[str]:
        return list(self.tables)

    def columns_of(self, table: str) -> list[str]:
        info = self.tables.get(table)
        return [c.name for c in info.columns] if info else []

    def all_columns(self) -> set[str]:
        cols: set[str] = set()
        for info in self.tables.values():
            cols.update(c.name for c in info.columns)
        return cols

    def ddl(self, tables: list[str] | None = None) -> str:
        names = tables if tables is not None else self.table_names
        return "\n\n".join(
            self.tables[t].ddl.strip() for t in names if t in self.tables
        )

    def to_prompt(self, tables: list[str] | None = None) -> str:
        """渲染成给 LLM 的表结构说明（含注释、低基数列取值、样例行）。"""
        names = tables if tables is not None else self.table_names
        blocks = []
        for name in names:
            info = self.tables.get(name)
            if info is None:
                continue
            lines = [f"### 表 {name}（{info.comment}，{info.row_count} 行）"]
            for col in info.columns:
                parts = [f"- {col.name} {col.type}"]
                if col.primary_key:
                    parts.append("主键")
                if col.not_null:
                    parts.append("非空")
                if col.comment:
                    parts.append(col.comment)
                if col.distinct_values:
                    shown = "、".join(col.distinct_values[:12])
                    more = " 等" if len(col.distinct_values) > 12 else ""
                    parts.append(f"取值: {shown}{more}")
                lines.append(" ".join(parts))
            if info.foreign_keys:
                fks = ", ".join(
                    f"{fk.column} -> {fk.ref_table}.{fk.ref_column}"
                    for fk in info.foreign_keys
                )
                lines.append(f"- 外键: {fks}")
            if info.sample_rows:
                for row in info.sample_rows[:2]:
                    lines.append(f"  示例: {row}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


def parse_schema(conn: sqlite3.Connection) -> DatabaseSchema:
    """从数据库连接中解析完整 schema。"""
    tables: dict[str, TableInfo] = {}
    table_rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    for name, ddl in table_rows:
        columns: list[ColumnInfo] = []
        for cid, col_name, col_type, not_null, _default, pk in conn.execute(
            f"PRAGMA table_info({_quote_ident(name)})"
        ).fetchall():
            distinct: list[str] = []
            if (col_type or "").upper() == "TEXT":
                # 低基数文本列（如状态、城市）抽取取值集合，显著提升 SQL 生成准确率
                values = [
                    str(r[0]) for r in conn.execute(
                        f"SELECT DISTINCT {_quote_ident(col_name)} FROM {_quote_ident(name)} "
                        f"WHERE {_quote_ident(col_name)} IS NOT NULL"
                    ).fetchall()
                ]
                if 0 < len(values) <= 15:
                    distinct = values
            columns.append(ColumnInfo(
                name=col_name,
                type=col_type or "TEXT",
                not_null=bool(not_null),
                primary_key=bool(pk),
                comment=COLUMN_COMMENTS.get((name, col_name), ""),
                distinct_values=distinct,
            ))
        foreign_keys = [
            ForeignKeyInfo(column=row[3], ref_table=row[2], ref_column=row[4])
            for row in conn.execute(f"PRAGMA foreign_key_list({_quote_ident(name)})").fetchall()
        ]
        row_count = conn.execute(
            f"SELECT COUNT(*) FROM {_quote_ident(name)}"
        ).fetchone()[0]
        sample_rows = conn.execute(
            f"SELECT * FROM {_quote_ident(name)} LIMIT 3"
        ).fetchall()
        tables[name] = TableInfo(
            name=name,
            comment=TABLE_COMMENTS.get(name, ""),
            columns=columns,
            foreign_keys=foreign_keys,
            row_count=row_count,
            ddl=ddl or "",
            sample_rows=sample_rows,
        )
    return DatabaseSchema(tables=tables)


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """以只读模式打开 SQLite 连接（URI mode=ro，任何写操作都会直接失败）。"""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
