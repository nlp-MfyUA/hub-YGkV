"""SQL 静态复核：语句形态、危险操作、表名字段名事实校验、LIMIT 兜底。

这一层是确定性的，不依赖模型判断；Agent B 负责语义层面的复核。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import config
from core import executor, schema as schema_mod

# 危险语句形态：只在「语句位置」匹配，避免误伤 replace() 之类的只读函数
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\binsert\s+(into|or)\b", "INSERT 写操作"),
    (r"\bupdate\s+[\w\"\[\]\.]+\s+set\b", "UPDATE 写操作"),
    (r"\bdelete\s+from\b", "DELETE 写操作"),
    (r"\breplace\s+into\b", "REPLACE 写操作"),
    (r"\bcreate\s+(table|index|view|trigger|temp|virtual)\b", "CREATE DDL"),
    (r"\bdrop\s+(table|index|view|trigger)\b", "DROP DDL"),
    (r"\balter\s+table\b", "ALTER DDL"),
    (r"\btruncate\s+table\b", "TRUNCATE"),
    (r"\battach\s+(database\b|$)", "ATTACH 数据库"),
    (r"\bdetach\s+(database\b|$)", "DETACH 数据库"),
    (r"\bpragma\b", "PRAGMA 指令"),
    (r"\bvacuum\b", "VACUUM 维护操作"),
    (r"\breindex\b", "REINDEX 维护操作"),
    (r"\b(begin|commit|rollback|savepoint)\b", "事务控制语句"),
]

_SELECT_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\b", re.IGNORECASE)
_SELECT_STAR_RE = re.compile(r"\bselect\s+(distinct\s+)?\*", re.IGNORECASE)
_CROSS_JOIN_RE = re.compile(r"\bcross\s+join\b", re.IGNORECASE)
_COMMA_FROM_RE = re.compile(r"\bfrom\s+[\w\"\[\]\.]+\s*,", re.IGNORECASE)
_TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*|\"[^\"]+\")", re.IGNORECASE)
_INTERNAL_TABLE_RE = re.compile(r"\bsqlite_(master|schema|sequence|stat\d?)\b", re.IGNORECASE)
_AGG_CALL_RE = re.compile(r"\b(count|sum|avg|min|max|total|group_concat)\s*\([^()]*\)", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)


def _top_level_select_list(code: str) -> str | None:
    """取最外层 SELECT 与 FROM 之间的列清单；解析失败返回 None。"""
    depth = 0
    last_select = None
    for match in re.finditer(r"[()]|\bselect\b|\bfrom\b", code, re.IGNORECASE):
        token = match.group(0).lower()
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0 and token == "select":
            last_select = match.end()
        elif depth == 0 and token == "from" and last_select is not None:
            return code[last_select : match.start()]
    return None


def _bare_columns_in_aggregate(select_list: str) -> list[str]:
    """找出「与聚合函数混用、却没有 GROUP BY」的裸列。"""
    items: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(select_list):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            items.append(select_list[start:index])
            start = index + 1
    items.append(select_list[start:])

    bare: list[str] = []
    for item in items:
        residual = _AGG_CALL_RE.sub(" ", item)
        residual = re.sub(r"\bas\s+[\w\"\[\]]+\s*$", " ", residual, flags=re.IGNORECASE)
        residual = residual.strip()
        if re.fullmatch(r"[A-Za-z_][\w\"\[\]\.]*", residual):
            bare.append(residual)
    return bare


@dataclass
class GuardResult:
    ok: bool
    sql: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    limit_appended: bool = False
    validation: executor.ValidationResult | None = None
    # True 表示错误不可通过「重新生成」修复（写操作、非查询语句），应立即终止
    fatal: bool = False


def strip_noncode(sql: str) -> str:
    """移除字符串字面量、注释，保留双引号标识符内容。"""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
        elif ch == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            out.append(" " + "".join(buf) + " ")
        elif ch == "[":
            end = sql.find("]", i + 1)
            i = n if end < 0 else end + 1
            out.append(" ")
        elif ch == "`":
            end = sql.find("`", i + 1)
            i = n if end < 0 else end + 1
            out.append(" ")
        elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
        elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _normalize(raw: str) -> str:
    sql = (raw or "").strip()
    sql = re.sub(r"^```[a-zA-Z]*\s*", "", sql)
    sql = re.sub(r"\s*```$", "", sql)
    return sql.strip().rstrip(";").strip()


def check_static(raw_sql: str, schema: schema_mod.SchemaInfo | None = None) -> GuardResult:
    schema = schema or schema_mod.get_schema()
    sql = _normalize(raw_sql)
    result = GuardResult(ok=False, sql=sql)

    if not sql:
        result.errors.append("SQL 为空")
        return result
    if len(sql) > config.MAX_SQL_LENGTH:
        result.errors.append(f"SQL 长度 {len(sql)} 超限（上限 {config.MAX_SQL_LENGTH}）")
        return result

    code = strip_noncode(sql)
    multi_statement = code.count(";") > 0

    # 先收集全部问题，避免只报第一个错误导致回炉反馈失真
    if not _SELECT_START.match(code):
        snippet = code.strip().split(maxsplit=1)[0][:20] if code.strip() else "空"
        result.errors.append(f"仅允许 SELECT / WITH 查询，当前语句以 `{snippet}` 开头")
        result.fatal = True

    for pattern, label in _DANGEROUS_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            result.errors.append(f"包含危险操作：{label}（本系统只读，禁止任何写入或结构变更）")
            result.fatal = True

    if multi_statement:
        result.errors.append("只允许单条语句，检测到额外的分号或语句分隔")

    # 写操作/非查询语句在只读白名单下不可能通过，直接判为不可修复，不再回炉
    if result.fatal or multi_statement:
        result.ok = False
        return result

    if _INTERNAL_TABLE_RE.search(code):
        result.warnings.append("访问了 SQLite 内部表（sqlite_*），通常不应出现在业务查询中")
    if _SELECT_STAR_RE.search(code):
        result.warnings.append("使用了 SELECT *，建议显式列出所需字段")
    if _CROSS_JOIN_RE.search(code):
        result.warnings.append("使用了 CROSS JOIN，确认不会产生笛卡尔积")
    if _COMMA_FROM_RE.search(code):
        result.warnings.append("FROM 子句中出现逗号连接，确认 JOIN 条件完整")

    # 聚合缺 GROUP BY：SQLite 不报错但结果不可信，直接判为阻断问题
    if _AGG_CALL_RE.search(code) and not _GROUP_BY_RE.search(code):
        select_list = _top_level_select_list(code)
        if select_list:
            bare = _bare_columns_in_aggregate(select_list)
            if bare:
                result.errors.append(
                    "聚合查询缺少 GROUP BY：SELECT 列表中的非聚合列 "
                    + "、".join(f"`{item}`" for item in bare)
                    + " 会返回任意一行的值，结果不可信"
                )

    # 引用的表名（仅用于展示与提示，权威校验交给 EXPLAIN）
    refs: list[str] = []
    for match in _TABLE_REF_RE.finditer(code):
        name = match.group(1).strip('"')
        if name.lower() in {"select", "values"}:
            continue
        if name not in refs:
            refs.append(name)
    result.tables = [
        info_name
        for info_name in refs
        if schema.table(info_name) is not None
    ]
    unknown = [name for name in refs if schema.table(name) is None]
    if unknown:
        result.warnings.append(
            "以下名称未在结构中匹配到（可能是 CTE 或别名）：" + ", ".join(unknown)
        )

    # LIMIT 兜底：仅在整条语句没有任何 LIMIT 时追加
    final_sql = sql
    if not _LIMIT_RE.search(code):
        final_sql = f"{sql}\nLIMIT {config.MAX_RESULT_ROWS}"
        result.limit_appended = True
        result.warnings.append(f"未写 LIMIT，已自动追加 LIMIT {config.MAX_RESULT_ROWS}")

    # SQLite 权威校验：语法、表名、字段名
    validation = executor.explain_validate(final_sql)
    result.validation = validation
    if not validation.ok:
        result.errors.append(f"SQLite 解析失败：{validation.error}")

    result.sql = final_sql
    result.ok = not result.errors
    return result


def feedback_text(sql: str, issues: list[str]) -> str:
    lines = ["上一轮生成的 SQL 未通过复核，必须修正后重新提交。", "", "SQL：", sql, "", "问题清单："]
    lines.extend(f"{idx}. {item}" for idx, item in enumerate(issues, start=1))
    return "\n".join(lines)
