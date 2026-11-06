"""Stage 4 · SQL 校验（纯静态 + 语义预检，不调用 LLM）。

六道检查，逐层收紧：

1. 语法解析      —— sqlglot 按 SQLite 方言解析，顺带拒绝多条语句；
2. 单条语句      —— 显式拦截分号分隔的多语句；
3. 语句类型      —— AST 中不允许出现任何写操作 / DDL / PRAGMA 等节点；
4. 表白名单      —— 所有物理表必须存在于 schema（CTE 名除外）；
5. 列白名单      —— 限定列解析到真实表后校验列存在（CTE / 派生表宽松跳过）；
6. 语义预检      —— 在只读连接上执行 EXPLAIN，让 SQLite 自己编译一遍，
                   捕捉静态分析漏掉的错误（如引用了未 JOIN 的表）。

任一检查失败即返回 ValidationResult(ok=False, error=...)，error 会作为
「SQL 改写」阶段的输入。
"""
from __future__ import annotations

from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError

from ..db import DatabaseSchema, connect_readonly
from ..models import STATUS_ERROR, STATUS_OK, STAGE_SQL_VALIDATE, ValidationCheck, ValidationResult

# 出现即拒绝的 AST 节点类型（写操作 / DDL / 环境类语句）
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.Pragma, exp.Set, exp.Command, exp.Use, exp.Transaction,
)

# 允许作为整条语句的顶层形态
ALLOWED_ROOTS = (exp.Select, exp.SetOperation, exp.With, exp.Subquery)


class SqlValidationStage:
    name = STAGE_SQL_VALIDATE

    def __init__(self, db_path: str | Path, schema: DatabaseSchema):
        self._db_path = Path(db_path)
        self._schema = schema
        self._known_tables = {t.lower() for t in schema.tables}

    def validate(self, sql: str) -> ValidationResult:
        checks: list[ValidationCheck] = []

        def add(name: str, ok: bool, detail: str = "") -> bool:
            checks.append(ValidationCheck(name=name, passed=ok, detail=detail))
            return ok

        if not sql or not sql.strip():
            return ValidationResult(False, "SQL 为空", [ValidationCheck("非空", False)])

        # -- 1+2. 语法解析 & 单条语句 ---------------------------------------
        # 注意：parse_one 不会拒绝多条语句（只会取第一条），必须用 parse() 的
        # 语句列表长度来判断，这样也不会误伤字符串字面量里的分号。
        try:
            statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
        except ParseError as exc:
            add("语法解析", False, str(exc))
            return self._fail(checks, f"SQL 语法错误: {exc}")
        except SqlglotError as exc:  # 方言不支持等
            add("语法解析", False, str(exc))
            return self._fail(checks, f"SQL 解析失败: {exc}")
        if len(statements) != 1:
            add("单条语句", False, f"检测到 {len(statements)} 条语句")
            return self._fail(checks, f"只允许单条 SQL 语句（检测到 {len(statements)} 条）")
        add("语法解析", True, "sqlglot(SQLite 方言) 解析通过")
        add("单条语句", True, "仅包含 1 条语句")
        parsed = statements[0]

        # -- 3. 语句类型（仅允许 SELECT / WITH-SELECT / UNION 等） ------------
        forbidden = sorted({
            type(node).__name__
            for node in parsed.walk() if isinstance(node, FORBIDDEN_NODES)
        })
        if forbidden:
            add("仅允许 SELECT", False, f"检测到非查询操作: {', '.join(forbidden)}")
            return self._fail(checks, f"安全策略：仅允许 SELECT，检测到 {', '.join(forbidden)}")
        if not isinstance(parsed, ALLOWED_ROOTS):
            add("仅允许 SELECT", False, f"顶层语句类型为 {type(parsed).__name__}")
            return self._fail(checks, "安全策略：仅允许 SELECT 查询")
        add("仅允许 SELECT", True)

        # -- 4. 表白名单 -----------------------------------------------------
        cte_names = {
            c.alias.lower() for c in parsed.find_all(exp.CTE) if c.alias
        }
        used_tables = [t.name.lower() for t in parsed.find_all(exp.Table)]
        unknown_tables = sorted({
            t for t in used_tables
            if t not in self._known_tables and t not in cte_names
        })
        if unknown_tables:
            add("表白名单", False, f"未知表: {', '.join(unknown_tables)}")
            return self._fail(checks, f"表不存在: {', '.join(unknown_tables)}"
                              f"（可选表: {', '.join(sorted(self._known_tables))}）")
        add("表白名单", True, f"引用表: {', '.join(sorted(set(used_tables))) or '（无）'}")

        # -- 5. 列白名单 -----------------------------------------------------
        column_error = self._check_columns(parsed)
        if column_error:
            add("列白名单", False, column_error)
            return self._fail(checks, column_error)
        add("列白名单", True, "所有可静态判定的列均存在于对应表中")

        # -- 6. 语义预检（EXPLAIN，只读连接） --------------------------------
        try:
            conn = connect_readonly(self._db_path)
            try:
                conn.execute("EXPLAIN " + sql)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - sqlite3.Error 及其子类统一处理
            add("语义检查(EXPLAIN)", False, str(exc))
            return self._fail(checks, f"SQLite 编译失败: {exc}")
        add("语义检查(EXPLAIN)", True, "SQLite 成功编译该查询")

        return ValidationResult(True, "", checks)

    # ------------------------------------------------------------------ 内部
    def _check_columns(self, parsed: exp.Expression) -> str:
        """返回错误描述；全部通过返回空串。

        宽松策略：限定符无法解析到真实表时（CTE / 派生表 / 函数命名空间），
        跳过该列并交给 EXPLAIN 兜底，避免误杀。
        """
        # 表别名 -> 真实表名
        alias_to_table: dict[str, str] = {}
        for table in parsed.find_all(exp.Table):
            if table.alias:
                alias_to_table[table.alias.lower()] = table.name.lower()
        # CTE 名与 SELECT 别名（HAVING / ORDER BY 可能引用它们）
        cte_names = {c.alias.lower() for c in parsed.find_all(exp.CTE) if c.alias}
        select_aliases = {a.alias.lower() for a in parsed.find_all(exp.Alias) if a.alias}

        all_columns = {c.lower() for c in self._schema.all_columns()}

        for col in parsed.find_all(exp.Column):
            qualifier = (col.table or "").lower()
            name = col.name.lower()
            if qualifier:
                real_table = alias_to_table.get(qualifier, qualifier)
                if real_table in self._known_tables:
                    table_columns = {c.lower() for c in self._schema.columns_of(real_table)}
                    if name not in table_columns:
                        return (f"列不存在: {qualifier}.{name}"
                                f"（{real_table} 表的列: {', '.join(self._schema.columns_of(real_table))}）")
                # 限定符是 CTE / 派生表 / 未知命名空间 -> 跳过，交给 EXPLAIN
            else:
                if name in select_aliases or name in cte_names or name in all_columns:
                    continue
                return f"列不存在: {name}（任何已选表中都没有该列）"
        return ""

    @staticmethod
    def _fail(checks: list[ValidationCheck], error: str) -> ValidationResult:
        failed = "；".join(c.detail for c in checks if not c.passed and c.detail)
        return ValidationResult(False, error or failed, checks)


__all__ = ["SqlValidationStage", "STATUS_ERROR", "STATUS_OK"]
