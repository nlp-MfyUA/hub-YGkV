"""Agent B：复核 SQL（字段名、主外键联查、危险操作、语义匹配）。

同样采用收口工具 submit_review；并通过 validate_sql 让 SQLite 给出事实性校验结果，
避免模型凭印象误判字段名。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from agents import Agent, ModelSettings, RunContextWrapper, StopAtTools, function_tool

import config
from core import executor, llm
from core import schema as schema_mod

_BASE_INSTRUCTIONS = """你是 SQL 复核员。唯一职责：判断待执行 SQL 是否安全、正确、能回答用户问题。你不改写 SQL，只提出问题。

数据库结构：
{schema}

复核清单（逐条核对）：
1. 表名与字段名：是否存在拼写错误、是否引用了不存在的表/列/别名、别名与原始列是否混淆。必须调用 validate_sql 获取 SQLite 的真实解析结果，以工具返回为准。
2. 主外键联查：每条 JOIN 的 ON 是否命中库中真实存在的外键关系；是否漏写 ON 造成笛卡尔积；多对多是否经过桥表（如 playlist_track）；连接方向是否会把一对多放大成重复计数；聚合前是否需要先去重。
3. 危险操作：出现 INSERT/UPDATE/DELETE/DDL/PRAGMA/ATTACH/多语句，一律不通过。
4. 语义匹配：过滤条件、聚合层级、时间范围、TopN 排序方向，是否真的回答了用户的问题。
5. SQLite 陷阱：整数除法截断、NULL 参与比较、日期按字符串比较、COUNT(*) 与 COUNT(DISTINCT) 的区别、GROUP BY 缺列、LIMIT 与 ORDER BY 不匹配。
6. 可满足性：若用户诉求本身无法在只读查询系统中实现（要求插入/更新/删除/清空/建表/改表/导出文件等），判 approved=false 且 unrecoverable=true，在 issues 里直接说明「只读系统无法执行写操作」；此时不要建议改写成另一个 SELECT。

判定标准：
- 只有 blocking 问题（执行会报错、结果会错、或存在危险操作）才 approved=false。
- 风格建议、可优化点写入 suggestion，不得因此否决；suggestion 不超过 120 字，只讲最关键的一条。
- issues 每条不超过 80 字，必须具体：指出哪一处、错在哪、应该怎么改。
- 没有把握的猜测不要写成 issue。

必须调用 submit_review 提交结论：
- approved：是否通过
- issues：阻断性问题列表，通过时为空数组
- risk：low / medium / high
- suggestion：非阻断的改进建议，可为空字符串
- unrecoverable：诉求是否根本无法在只读系统中完成
"""


@dataclass
class ReviewResult:
    approved: bool
    issues: list[str] = field(default_factory=list)
    risk: str = "low"
    suggestion: str = ""
    source: str = "llm"  # llm | llm-fallback | static | error
    model: str = ""
    # 用户诉求本身无法在只读系统中完成（要求增删改、DDL 等），重写 SQL 也无解
    unrecoverable: bool = False


@dataclass
class CheckContext:
    result: ReviewResult | None = None


@function_tool
def validate_sql(sql: str) -> str:
    """用 SQLite 解析这条 SQL，返回真实的语法/表名/字段名检查结果与执行计划（不读取业务数据）。

    Args:
        sql: 待检查的 SQL。
    """
    validation = executor.explain_validate(sql)
    if validation.ok:
        plan = "\n".join(validation.plan[:12]) or "（无计划输出）"
        return f"解析通过。\n执行计划：\n{plan}"
    return f"解析失败：{validation.error}"


@function_tool
def submit_review(
    ctx: RunContextWrapper[CheckContext],
    approved: bool,
    issues: list[str],
    risk: str,
    suggestion: str,
    unrecoverable: bool,
) -> str:
    """提交复核结论。必须调用本工具作为最终答复。

    Args:
        approved: 是否通过复核。
        issues: 阻断性问题列表；通过时传空数组。
        risk: 风险等级，low / medium / high。
        suggestion: 非阻断的改进建议，可为空字符串。
        unrecoverable: 用户诉求本身是否无法在只读查询系统中完成（如要求增删改、DDL、清空表）。若为 true，重写 SQL 也不会通过。
    """
    normalized_risk = (risk or "low").strip().lower()
    if normalized_risk not in {"low", "medium", "high"}:
        normalized_risk = "medium"
    ctx.context.result = ReviewResult(
        approved=bool(approved),
        issues=[item for item in (issues or []) if isinstance(item, str) and item.strip()],
        risk=normalized_risk,
        suggestion=(suggestion or "").strip(),
        source="llm",
        unrecoverable=bool(unrecoverable),
    )
    return "已接收"


_TOOLS = [validate_sql, submit_review]


def build_agent(schema: schema_mod.SchemaInfo | None = None, model_name: str | None = None) -> Agent:
    info = schema or schema_mod.get_schema()
    return Agent(
        name="sql_reviewer",
        instructions=_BASE_INSTRUCTIONS.format(schema=info.prompt()),
        model=llm.model(model_name or config.CHECK_MODEL),
        tools=_TOOLS,
        tool_use_behavior=StopAtTools(stop_at_tool_names=["submit_review"]),
        model_settings=ModelSettings(temperature=0.0, max_tokens=900),
    )


def _parse_fallback(output: str) -> ReviewResult | None:
    text = (output or "").strip()
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    approved = bool(payload.get("approved"))
    issues = payload.get("issues") or []
    if isinstance(issues, str):
        issues = [issues]
    return ReviewResult(
        approved=approved,
        issues=[str(item) for item in issues if str(item).strip()],
        risk=str(payload.get("risk") or ("low" if approved else "high")).lower(),
        suggestion=str(payload.get("suggestion") or ""),
        source="llm",
        unrecoverable=bool(payload.get("unrecoverable")),
    )


async def _attempt(
    agent: Agent,
    payload: str,
    *,
    timeout: float | None = None,
) -> tuple[llm.AgentRun, ReviewResult]:
    context = CheckContext()
    run = await llm.run_agent(
        agent, payload, context=context, max_turns=4, retries=0, timeout=timeout
    )
    model_name = getattr(getattr(agent, "model", None), "model", "") or ""
    if context.result is not None:
        context.result.model = model_name
        return run, context.result
    if run.ok:
        parsed = _parse_fallback(str(run.output or ""))
        if parsed is not None:
            parsed.model = model_name
            return run, parsed
    return run, ReviewResult(
        approved=False,
        issues=[f"复核未产出结论：{run.error or '模型未调用 submit_review'}"],
        risk="high",
        suggestion="",
        source="error",
        model=model_name,
    )


async def review_sql(
    question: str,
    sql: str,
    *,
    agent: Agent | None = None,
    note: str | None = None,
) -> tuple[llm.AgentRun, ReviewResult]:
    agent = agent or build_agent()
    payload = f"用户问题：{question}\n\n待复核 SQL：\n{sql}"
    if note:
        payload = f"{payload}\n\n补充说明：{note}"

    run, review = await _attempt(agent, payload, timeout=config.CHECK_TIMEOUT_SECONDS)
    if review.source != "error":
        return run, review

    # 主复核模型尾延迟/异常：降级到备用模型，结论标注 llm-fallback
    if config.CHECK_FALLBACK_MODEL and config.CHECK_FALLBACK_MODEL != config.CHECK_MODEL:
        fallback_agent = build_agent(model_name=config.CHECK_FALLBACK_MODEL)
        run2, review2 = await _attempt(
            fallback_agent, payload, timeout=config.CHECK_TIMEOUT_SECONDS * 2
        )
        run2.tools = [
            {"name": "fallback", "args": f"主模型异常：{(run.error or '')[:100]}"}
        ] + run2.tools
        if review2.source == "llm":
            review2.source = "llm-fallback"
        return run2, review2
    return run, review
