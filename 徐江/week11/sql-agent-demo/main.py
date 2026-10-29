"""CLI 入口。

用法：
    python main.py init-db                     # 重建示例数据库
    python main.py ask "每个城市的用户数量"     # 单条问题，逐 stage 演示
    python main.py eval                        # 批量评测（15 条）+ Markdown 报告
    python main.py eval --ids 1,5,8            # 只跑子集

常用参数（ask / eval 均支持）：
    --config PATH      指定配置文件（默认 config.local.yaml）
    --provider mock    临时切换到离线模拟客户端（无需 API Key）
    --model NAME       覆盖模型名
    --max-attempts N   覆盖工作流重试上限
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows 控制台中文输出保护
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

from sql_agent.config import Config, ConfigError
from sql_agent.db import build_database
from sql_agent.llm import LLMError, create_llm
from sql_agent.models import STATUS_ERROR, STATUS_OK
from sql_agent.workflow import SqlAgentWorkflow

from eval.report import render_console, write_markdown_report
from eval.runner import run_eval
from eval.test_queries import register_mock_knowledge_from_tests, select_queries

PROJECT_ROOT = Path(__file__).resolve().parent


# --------------------------------------------------------------------- ask
def cmd_ask(args, config: Config) -> int:
    if args.provider == "mock":
        _register_mock()
    workflow = SqlAgentWorkflow(config, create_llm(config))
    result = workflow.run(args.question)
    _print_workflow(result)
    return 0 if result.success else 1


def _print_workflow(result) -> None:
    print()
    print("═" * 72)
    print(f"问题：{result.question}")
    print("═" * 72)
    for trace in result.traces:
        mark = {"ok": "✅", "error": "❌", "skipped": "⏭️"}.get(trace.status, "?")
        attempt = f"（第 {trace.attempt} 次尝试）" if trace.attempt > 1 else ""
        print(f"[{mark}] {trace.stage}{attempt}  {_fmt_ms(trace.duration_ms)}")
        if trace.input_brief:
            print(f"    输入: {trace.input_brief}")
        if trace.output_brief:
            print(f"    输出: {trace.output_brief}")
        if trace.detail:
            print(f"    说明: {trace.detail}")
    print("─" * 72)
    if result.success and result.execution is not None:
        print(f"最终 SQL:\n{result.final_sql}")
        print(f"\n执行结果（{result.execution.row_count} 行"
              f"{'，已截断' if result.execution.truncated else ''}）：")
        for row in result.execution.rows[:10]:
            print("  " + " | ".join(str(v) for v in row))
        if result.summary:
            print(f"\nLLM 总结：{result.summary}")
    else:
        print(f"❌ 工作流失败：{result.error}")
        if result.final_sql:
            print(f"最后一次 SQL：\n{result.final_sql}")
    print(f"\n总耗时 {_fmt_ms(result.total_duration_ms)}｜"
          f"token {result.usage.total_tokens}｜尝试 {result.attempts} 次")
    print("═" * 72)


# --------------------------------------------------------------------- eval
def cmd_eval(args, config: Config) -> int:
    if args.provider == "mock":
        _register_mock()
    queries = select_queries(args.ids)
    llm = create_llm(config)
    print(f"开始批量评测：{len(queries)} 条问题，模型 {config.llm.provider}/{llm.model}")

    def progress(index: int, total: int, outcome) -> None:
        r = outcome.result
        mark = "✅" if r.success else "❌"
        match = {"exact": "✅", "loose": "✅", "mismatch": "❌"}.get(outcome.match, "⚠️")
        print(f"  [{index}/{total}] {outcome.query.qid} "
              f"{_truncate(outcome.query.question, 24)} "
              f"执行{mark} 结果{match} 尝试{r.attempts}次 "
              f"{_fmt_ms(r.total_duration_ms)}")

    report = run_eval(config, llm, queries, on_progress=progress)
    print(render_console(report))

    schema_ddl = ""
    try:
        from sql_agent.db import connect_readonly, parse_schema
        conn = connect_readonly(config.db.path)
        schema = parse_schema(conn)
        conn.close()
        schema_ddl = schema.ddl()
    except Exception:  # noqa: BLE001 - 附录失败不影响主流程
        pass
    report_path = write_markdown_report(report, PROJECT_ROOT / "reports",
                                        schema_ddl=schema_ddl)
    print(f"Markdown 报告已生成: {report_path}")
    return 0


# --------------------------------------------------------------------- init-db
def cmd_init_db(args, config: Config) -> int:
    path = build_database(config.db.path, rebuild=True)
    print(f"示例数据库已重建: {path.resolve()}")
    from sql_agent.db import connect_readonly, parse_schema
    conn = connect_readonly(path)
    schema = parse_schema(conn)
    conn.close()
    for name in schema.table_names:
        print(f"  {name}: {schema.tables[name].row_count} 行")
    return 0


# --------------------------------------------------------------------- 入口
def _register_mock() -> None:
    register_mock_knowledge_from_tests()


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def _truncate(text: str, width: int) -> str:
    import unicodedata
    out = ""
    for ch in text:
        w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in out + ch)
        if w > width:
            break
        out += ch
    return out + ("…" if len(out) < len(text) else "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="固定流程 SQL Agent 工作流 Demo（数据库解析→选表→生成→校验→改写→执行→汇总）"
    )
    # 通用参数放在主命令后、子命令前；子命令上也注册同名参数（default=SUPPRESS，
    # 未提供时不会覆盖主命令已解析的值），两种位置都可以写。
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.local.yaml）")
    parser.add_argument("--provider", choices=["deepseek", "mock"], default=None,
                        help="覆盖配置中的 llm.provider")
    parser.add_argument("--model", default=None, help="覆盖配置中的 llm.model")
    parser.add_argument("--max-attempts", type=int, default=None,
                        help="覆盖工作流重试上限")
    parser.add_argument("--rebuild-db", action="store_true", help="先重建示例数据库")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ask = sub.add_parser("ask", help="单条问题演示，逐 stage 打印输入输出")
    p_ask.add_argument("question", help="自然语言问题")

    p_eval = sub.add_parser("eval", help="批量评测 + 生成 Markdown 报告")
    p_eval.add_argument("--ids", default=None, help="只跑子集，如 1,5,8 或 1-5")
    p_eval.add_argument("--no-summarize", action="store_true",
                        help="跳过结果汇总阶段（省 token）")

    sub.add_parser("init-db", help="重建示例数据库")

    # 子命令上的同名通用参数（缺省不设置，避免覆盖主命令的解析结果）
    for p in (p_ask, p_eval):
        p.add_argument("--provider", choices=["deepseek", "mock"],
                       default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        p.add_argument("--model", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        p.add_argument("--max-attempts", type=int, default=argparse.SUPPRESS,
                       help=argparse.SUPPRESS)
        p.add_argument("--rebuild-db", action="store_true", default=argparse.SUPPRESS,
                       help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.load(args.config)
    except ConfigError as exc:
        print(f"[config] {exc}")
        return 2

    # CLI 覆盖
    if args.provider:
        config.llm.provider = args.provider
    if args.model:
        config.llm.model = args.model
    if args.max_attempts:
        config.eval.max_attempts = args.max_attempts
    if getattr(args, "no_summarize", False):
        config.eval.summarize = False
    if args.rebuild_db or args.command == "init-db":
        build_database(config.db.path, rebuild=True)

    handlers = {"ask": cmd_ask, "eval": cmd_eval, "init-db": cmd_init_db}
    try:
        return handlers[args.command](args, config)
    except LLMError as exc:
        print(f"[llm] {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
