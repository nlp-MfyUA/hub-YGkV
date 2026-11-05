"""
阶段 4：SQL 校验里的静态检查。

分两层：
    静态检查（本文件）：只允许单条 SELECT / WITH 查询、禁止写操作关键字、
                        引用的表必须真实存在；
    动态检查（DBParser.check_sql）：交给 sqlite 用 EXPLAIN 编译，语法、字段名错误都会暴露。

真正的兜底是数据库以只读方式打开（mode=ro + query_only），
静态检查的作用是尽早给出**可读的错误信息**，喂给「SQL 改写」阶段。
"""
from __future__ import annotations

import re

# 写操作 / 危险语句关键字。真正的执行会用只读连接拦住，这里只是提前报错。
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "attach", "detach", "pragma", "vacuum", "reindex",
    "load_extension", "grant", "revoke",
}

_TABLE_REF = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w$]*)", re.I)
_CTE_NAME = re.compile(r"(?:\bwith\s+(?:recursive\s+)?|,\s*)([A-Za-z_][\w$]*)\s+as\s*\(", re.I)
_WORD = re.compile(r"[A-Za-z_][\w$]*")


def normalize_sql(raw: str) -> str:
    """把模型输出清洗成一条纯 SQL：去 markdown 围栏、去 'sql' 前缀、去结尾分号。"""
    text = (raw or "").strip()

    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        text = fence.group(1).strip()

    # 去掉开头的 ```sql / sql 标记（没有闭合围栏时）
    text = re.sub(r"^\s*```\s*(?:sql)?\s*", "", text, flags=re.I)
    text = re.sub(r"^\s*sql\s*\n", "", text, flags=re.I)

    text = text.strip().strip("`").strip()
    return text.rstrip().rstrip(";").strip()


def strip_literals_and_comments(sql: str) -> str:
    """去掉注释、字符串字面量，并把带引号的标识符还原成裸标识符。

    这样按关键字做检查时，`WHERE Name = 'delete'` 不会被误判成 DELETE 语句。
    """
    out: list[str] = []
    i, n = 0, len(sql)

    while i < n:
        ch = sql[i]

        # -- 行注释
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
            continue

        # /* 块注释 */
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue

        # '字符串'
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":  # '' 转义
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append("''")
            continue

        # "标识符" / `标识符` / [标识符]
        if ch in ('"', "`", "["):
            closing = {"\"": "\"", "`": "`", "[": "]"}[ch]
            end = sql.find(closing, i + 1)
            if end == -1:
                out.append(sql[i:])
                break
            out.append(sql[i + 1 : end])
            i = end + 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def extract_tables(sql: str) -> set[str]:
    """从 FROM / JOIN 子句里提取被引用的表名（含 CTE 名）。"""
    stripped = strip_literals_and_comments(sql)
    return {name.lower() for name in _TABLE_REF.findall(stripped)}


def extract_cte_names(sql: str) -> set[str]:
    stripped = strip_literals_and_comments(sql)
    return {name.lower() for name in _CTE_NAME.findall(stripped)}


def check_static(sql: str, valid_tables: list[str] | set[str]) -> tuple[bool, str]:
    """静态校验，返回 (是否通过, 错误信息)。"""
    if not sql.strip():
        return False, "SQL 为空"

    stripped = strip_literals_and_comments(sql)

    # 1. 只允许一条语句
    body = stripped.strip().rstrip(";").strip()
    if ";" in body:
        return False, "只允许执行一条 SQL 语句，检测到多条语句"

    # 2. 只允许 SELECT / WITH
    words = _WORD.findall(body.lower())
    if not words:
        return False, "SQL 为空"
    first_word = words[0]
    if first_word not in {"select", "with"}:
        return False, f"只允许 SELECT 查询，当前语句以 {first_word.upper()} 开头"

    # 3. 禁止写操作 / 危险关键字
    forbidden = sorted(FORBIDDEN_KEYWORDS.intersection(words))
    if forbidden:
        return False, "SQL 中包含禁止的关键字：" + ", ".join(forbidden)

    # 4. 引用的表必须存在（CTE 名除外）
    known = {t.lower() for t in valid_tables} | extract_cte_names(sql)
    unknown = sorted(extract_tables(sql) - known)
    if unknown:
        return False, "SQL 引用了不存在的表：" + ", ".join(unknown) + (
            "；可用的表：" + ", ".join(sorted(valid_tables))
        )

    return True, "ok"
