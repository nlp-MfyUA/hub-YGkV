"""工作流与评测共用的数据模型。

每个 Stage 执行后都会产出一个 StageTrace（留痕），最终汇入 WorkflowResult，
供 CLI 演示逐 stage 打印、也供评测报告引用。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ----------------------------------------------------------- stage 名称常量
STAGE_DB_PARSE = "数据库解析"
STAGE_TABLE_SELECT = "Table 选择"
STAGE_SQL_GENERATE = "SQL 生成"
STAGE_SQL_VALIDATE = "SQL 校验"
STAGE_SQL_REWRITE = "SQL 改写"
STAGE_SQL_EXECUTE = "SQL 执行"
STAGE_SUMMARIZE = "结果汇总"

ALL_STAGES = [
    STAGE_DB_PARSE,
    STAGE_TABLE_SELECT,
    STAGE_SQL_GENERATE,
    STAGE_SQL_VALIDATE,
    STAGE_SQL_REWRITE,
    STAGE_SQL_EXECUTE,
    STAGE_SUMMARIZE,
]

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


@dataclass
class LLMUsage:
    """一次工作流运行累计的 LLM token 用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

    def add_trace(self, trace: "StageTrace") -> None:
        if trace.usage:
            self.prompt_tokens += trace.usage.prompt_tokens
            self.completion_tokens += trace.usage.completion_tokens
            self.total_tokens += trace.usage.total_tokens
            self.calls += 1


@dataclass
class StageTrace:
    """单个 stage 的执行留痕。"""

    stage: str
    status: str                       # ok / error / skipped
    input_brief: str = ""             # 输入摘要（可能截断）
    output_brief: str = ""            # 输出摘要（可能截断）
    detail: str = ""                  # 补充说明（错误原因 / 校验明细 / 缓存标记等）
    duration_ms: float = 0.0
    attempt: int = 0                  # 属于第几次尝试（改写阶段 > 1）
    usage: LLMUsage | None = None     # 调用了 LLM 的 stage 记录 token 用量
    llm_failed: bool = False          # True 表示 LLM 接口本身调用失败（重试无意义，工作流应短路）


@dataclass
class ValidationCheck:
    """单项校验结果。"""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationResult:
    ok: bool
    error: str = ""                   # 未通过时的错误描述（会喂给改写阶段）
    checks: list[ValidationCheck] = field(default_factory=list)

    def checks_summary(self) -> str:
        return "  ".join(
            f"{'✅' if c.passed else '❌'}{c.name}" for c in self.checks
        )


@dataclass
class ExecutionResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False           # 是否触发了行数上限
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class WorkflowResult:
    """一条问题的完整工作流结果。"""

    question: str
    success: bool
    final_sql: str = ""               # 最后一次尝试的 SQL
    attempts: int = 0                 # 生成 + 改写的总尝试次数
    traces: list[StageTrace] = field(default_factory=list)
    execution: ExecutionResult | None = None
    summary: str = ""                 # LLM 结果汇总
    error: str = ""                   # 失败时的兜底说明
    total_duration_ms: float = 0.0
    usage: LLMUsage = field(default_factory=LLMUsage)

    def trace_of(self, stage: str) -> StageTrace | None:
        for t in self.traces:
            if t.stage == stage:
                return t
        return None
