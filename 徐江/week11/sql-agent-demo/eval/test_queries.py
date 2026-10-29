"""批量评测测试集：15 条自然语言问题 + 对应 gold SQL。

覆盖三类难度：
- 简单（5 条）：单表过滤 / 计数 / 极值 / 低库存筛选；
- 中等（6 条）：分组聚合、年月聚合、状态分布、两表 join TopN、用户消费排行；
- 复杂（4 条）：三表 join 品类销售额、子查询（超均值用户）、反连接（未下单用户）、
  区间 + 条件 + 均值客单价。

gold SQL 基于 data/ecommerce.db 的确定性种子数据编写，用于结果正确性比对。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestQuery:
    qid: str            # Q1..Q15
    question: str       # 自然语言问题
    gold_sql: str       # 标准答案 SQL
    category: str       # 考察点
    difficulty: str     # 简单 / 中等 / 复杂


TEST_QUERIES: list[TestQuery] = [
    TestQuery(
        "Q1", "数据库里一共有多少个用户？",
        "SELECT COUNT(*) AS user_count FROM users",
        "单表计数", "简单",
    ),
    TestQuery(
        "Q2", "北京有多少个用户？",
        "SELECT COUNT(*) AS user_count FROM users WHERE city = '北京'",
        "单表条件计数", "简单",
    ),
    TestQuery(
        "Q3", "商品一共有多少个品类？",
        "SELECT COUNT(DISTINCT category) AS category_count FROM products",
        "去重计数", "简单",
    ),
    TestQuery(
        "Q4", "价格最高的商品是什么？多少钱？",
        "SELECT product_name, price FROM products ORDER BY price DESC LIMIT 1",
        "排序取极值", "简单",
    ),
    TestQuery(
        "Q5", "库存不足 50 件的商品有哪些？按库存从少到多列出来",
        "SELECT product_name, stock FROM products WHERE stock < 50 ORDER BY stock ASC",
        "条件筛选 + 排序", "简单",
    ),
    TestQuery(
        "Q6", "每个城市分别有多少用户？按用户数从多到少排序",
        "SELECT city, COUNT(*) AS user_count FROM users GROUP BY city "
        "ORDER BY user_count DESC",
        "分组聚合", "中等",
    ),
    TestQuery(
        "Q7", "2024 年每个月的订单量和销售总额分别是多少？",
        "SELECT substr(order_date, 1, 7) AS month, COUNT(*) AS order_count, "
        "SUM(total_amount) AS total_sales FROM orders "
        "WHERE order_date >= '2024-01-01' AND order_date <= '2024-12-31' "
        "GROUP BY substr(order_date, 1, 7) ORDER BY month",
        "日期截取 + 年月聚合", "中等",
    ),
    TestQuery(
        "Q8", "所有已完成订单的总金额是多少？",
        "SELECT SUM(total_amount) AS total FROM orders WHERE status = '已完成'",
        "条件求和", "中等",
    ),
    TestQuery(
        "Q9", "统计每种订单状态下的订单数量",
        "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status "
        "ORDER BY order_count DESC",
        "枚举值分组", "中等",
    ),
    TestQuery(
        "Q10", "销量前 10 的商品是什么？各卖了多少件？",
        "SELECT p.product_name, SUM(oi.quantity) AS total_qty "
        "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
        "GROUP BY p.product_id, p.product_name "
        "ORDER BY total_qty DESC, p.product_id LIMIT 10",
        "两表 join + TopN", "中等",
    ),
    TestQuery(
        "Q11", "累计消费金额前 5 的用户是谁？各消费了多少？",
        "SELECT u.user_name, SUM(o.total_amount) AS total_spent "
        "FROM users u JOIN orders o ON u.user_id = o.user_id "
        "WHERE o.status = '已完成' "
        "GROUP BY u.user_id, u.user_name "
        "ORDER BY total_spent DESC, u.user_id LIMIT 5",
        "join + 条件聚合排行", "中等",
    ),
    TestQuery(
        "Q12", "每个商品品类的销售总额是多少？按销售额从高到低排序",
        "SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi "
        "JOIN products p ON oi.product_id = p.product_id "
        "JOIN orders o ON oi.order_id = o.order_id "
        "WHERE o.status = '已完成' "
        "GROUP BY p.category ORDER BY revenue DESC",
        "三表 join + 表达式聚合", "复杂",
    ),
    TestQuery(
        "Q13", "哪些用户的累计消费金额超过了整体平均水平？",
        "SELECT u.user_name, SUM(o.total_amount) AS total_spent "
        "FROM users u JOIN orders o ON u.user_id = o.user_id "
        "WHERE o.status = '已完成' "
        "GROUP BY u.user_id, u.user_name "
        "HAVING SUM(o.total_amount) > "
        "(SELECT AVG(total_amount) FROM orders WHERE status = '已完成') "
        "ORDER BY total_spent DESC",
        "子查询 + HAVING", "复杂",
    ),
    TestQuery(
        "Q14", "找出从来没有下过单的用户",
        "SELECT u.user_id, u.user_name, u.city FROM users u "
        "LEFT JOIN orders o ON u.user_id = o.user_id "
        "WHERE o.order_id IS NULL ORDER BY u.user_id",
        "左连接反连接", "复杂",
    ),
    TestQuery(
        "Q15", "2024 年下半年，每月已完成订单的平均客单价是多少？",
        "SELECT substr(o.order_date, 1, 7) AS month, "
        "AVG(o.total_amount) AS avg_order_value FROM orders o "
        "WHERE o.order_date >= '2024-07-01' AND o.order_date <= '2024-12-31' "
        "AND o.status = '已完成' "
        "GROUP BY substr(o.order_date, 1, 7) ORDER BY month",
        "区间 + 条件 + 均值", "复杂",
    ),
]

# gold SQL 涉及的表（用于注册 MockClient 的选表模拟）
GOLD_TABLES: dict[str, list[str]] = {
    "Q1": ["users"],
    "Q2": ["users"],
    "Q3": ["products"],
    "Q4": ["products"],
    "Q5": ["products"],
    "Q6": ["users"],
    "Q7": ["orders"],
    "Q8": ["orders"],
    "Q9": ["orders"],
    "Q10": ["order_items", "products"],
    "Q11": ["users", "orders"],
    "Q12": ["order_items", "products", "orders"],
    "Q13": ["users", "orders"],
    "Q14": ["users", "orders"],
    "Q15": ["orders"],
}

# Mock 模式下 Q8 首次生成时故意写错列名（orders.amount -> orders.total_amount），
# 用于演示「SQL 校验失败 → SQL 改写 → 重试通过」的完整回路。
MOCK_FIRST_ATTEMPT_BUGS: dict[str, str] = {
    "Q8": "SELECT SUM(orders.amount) AS total FROM orders WHERE status = '已完成'",
}


def select_queries(ids: str | None = None) -> list[TestQuery]:
    """按 --ids 过滤，支持 '1,5,8' 与 '1-5' 两种写法。"""
    if not ids:
        return list(TEST_QUERIES)
    wanted: set[str] = set()
    for part in ids.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            wanted.update(f"Q{i}" for i in range(int(start), int(end) + 1))
        else:
            wanted.add(f"Q{int(part)}")
    selected = [q for q in TEST_QUERIES if q.qid in wanted]
    if not selected:
        raise ValueError(f"--ids {ids!r} 没有匹配到任何测试问题")
    return selected


def register_mock_knowledge_from_tests() -> None:
    """把测试集的 gold SQL / 选表结果 / 首错用例注册进 MockClient。

    CLI（main.py）与后端（backend/service.py）在 mock 模式下共用，
    保证两条入口的 mock 行为一致（包括 Q8 的「校验失败 → 改写」演示）。
    """
    from sql_agent.llm import register_mock_knowledge

    register_mock_knowledge(
        sql_by_question={q.question: q.gold_sql for q in TEST_QUERIES},
        tables_by_question={q.question: GOLD_TABLES[q.qid] for q in TEST_QUERIES},
        first_attempt_bugs={
            q.question: MOCK_FIRST_ATTEMPT_BUGS[q.qid]
            for q in TEST_QUERIES if q.qid in MOCK_FIRST_ATTEMPT_BUGS
        },
    )
