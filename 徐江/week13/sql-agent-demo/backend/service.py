"""服务层：把 SqlAgentWorkflow 与批量评测封装成 API 可用的服务。

职责边界：
- 前端（Streamlit）只通过 HTTP 调用本服务，不直接 import sql_agent；
- 本服务是唯一接触 sql_agent / eval 核心包的层次；
- 配置加载失败或 LLM 不可用时进入「降级状态」：health 接口如实反映，
  query/eval 返回 503，而不是让服务器启动失败。

week13 起工作流由 LangGraph 驱动（checkpointer + thread_id），本层新增：
- 共享一个 checkpointer（memory / sqlite 按配置），所有工作流实例共用，
  按 thread_id 即可回查任意一次运行的状态快照；
- stream_query()：逐节点产出 SSE 事件（实时进度）；
- graph_mermaid() / state_snapshot()：LangGraph 图内省与状态回查。
"""
from __future__ import annotations

import copy
import dataclasses
import sys
from pathlib import Path
from typing import Iterator

# 保证无论从哪个工作目录启动 uvicorn，都能导入项目核心包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sql_agent.checkpoint import create_checkpointer
from sql_agent.config import Config, ConfigError
from sql_agent.llm import LLMError, chat_model_name, create_chat_model
from sql_agent.workflow import SqlAgentWorkflow
from eval.report import render_markdown, write_markdown_report
from eval.runner import run_eval
from eval.test_queries import select_queries


class WorkflowService:
    """SQL Agent 工作流服务（进程内单例）。"""

    def __init__(self, config_path: str | None = None):
        self._config: Config | None = None
        self._llm = None
        self._workflow: SqlAgentWorkflow | None = None
        self._checkpointer = None          # LangGraph checkpointer（进程内共享）
        self._last_results: dict[str, dict] = {}  # thread_id -> 最近一次结果（供 /api/state 快速回查）
        self._error: str | None = None
        try:
            self._config = Config.load(config_path)
            self._resolve_paths()
            if self._config.llm.provider == "mock":
                # mock 模式：注册测试集知识，保证 CLI 与后端行为一致
                from eval.test_queries import register_mock_knowledge_from_tests
                register_mock_knowledge_from_tests()
            self._llm = create_chat_model(self._config)
            # checkpointer 按配置创建（memory / sqlite），所有工作流实例共用，
            # 因此任意线程的状态都能从任一实例回查
            self._checkpointer = create_checkpointer(self._config)
            self._workflow = SqlAgentWorkflow(self._config, self._llm,
                                              checkpointer=self._checkpointer)
        except (ConfigError, LLMError) as exc:
            self._error = str(exc)
        except Exception as exc:
            # 兜底：LLM 客户端构造等意外错误（如 SSL_CERT_FILE 指向无效路径）
            # 只应让服务降级，而不是让整个服务器启动失败
            self._error = f"工作流服务初始化失败: {type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------ 工具
    def _resolve_paths(self) -> None:
        """把配置里的相对路径解析为相对项目根目录的绝对路径。"""
        db_path = Path(self._config.db.path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        self._config.db.path = str(db_path)
        ckpt = Path(self._config.graph.checkpoint_path)
        if not ckpt.is_absolute():
            self._config.graph.checkpoint_path = str(PROJECT_ROOT / ckpt)

    def _require_workflow(self, max_attempts: int | None,
                          summarize: bool | None) -> SqlAgentWorkflow:
        if self._workflow is None:
            raise LLMError(self._error or "工作流服务未初始化")
        if max_attempts is None and summarize is None:
            return self._workflow
        # 按请求参数构造一次性工作流（深拷贝配置，避免污染单例）
        cfg = copy.deepcopy(self._config)
        if max_attempts is not None:
            cfg.eval.max_attempts = max(1, max_attempts)
        if summarize is not None:
            cfg.eval.summarize = summarize
        try:
            llm = create_chat_model(cfg)
        except (ConfigError, LLMError):
            raise
        except Exception as exc:
            raise LLMError(
                f"LLM 客户端创建失败: {type(exc).__name__}: {exc}"
            ) from exc
        return SqlAgentWorkflow(cfg, llm, checkpointer=self._checkpointer)

    # ------------------------------------------------------------------ 接口
    def health(self) -> dict:
        if self._error or self._config is None:
            return {"status": "error", "detail": self._error or "服务未初始化"}
        try:
            schema = self.schema()
            table_count = len(schema["tables"])
        except Exception as exc:  # noqa: BLE001 - 库文件损坏等也如实反映
            return {"status": "degraded", "detail": f"schema 读取失败: {exc}",
                    "provider": self._config.llm.provider,
                    "model": chat_model_name(self._llm)}
        return {
            "status": "ok",
            "provider": self._config.llm.provider,
            "model": chat_model_name(self._llm),
            "base_url": self._config.llm.base_url,
            "db_path": self._config.db.path,
            "max_attempts": self._config.eval.max_attempts,
            "row_limit": self._config.eval.row_limit,
            "table_count": table_count,
        }

    def query(self, question: str, *, max_attempts: int | None = None,
              summarize: bool | None = None,
              thread_id: str | None = None) -> dict:
        """执行一次工作流，返回含全部 stage 留痕的结果字典。

        thread_id 缺省自动生成（LangGraph 每次运行一个线程）；结果会登记到
        进程内注册表，随后可用 GET /api/state/{thread_id} 回查。
        """
        workflow = self._require_workflow(max_attempts, summarize)
        result = workflow.run(question, thread_id=thread_id)
        payload = dataclasses.asdict(result)
        self._last_results[result.thread_id] = payload
        return payload

    # ------------------------------------------------------------------ 流式
    def stream_query(self, question: str, *, max_attempts: int | None = None,
                     summarize: bool | None = None,
                     thread_id: str | None = None) -> Iterator[dict]:
        """逐节点流式执行工作流，产出 SSE 事件字典（event/data 两键）。

        事件序列：
        - {"event": "start",   "data": {"thread_id": ...}}
        - {"event": "node",    "data": {"node": 节点名, "update": 增量}}
        - {"event": "result",  "data": {"thread_id": ..., "result": 完整结果}}
        - {"event": "error",   "data": {"detail": 错误信息}}（异常时，随后结束）

        流式驱动复用同一个 LangGraph 状态机（graph.stream(stream_mode="updates")），
        与非流式 query() 的最终结果完全一致。
        """
        workflow = self._require_workflow(max_attempts, summarize)
        tid = thread_id or SqlAgentWorkflow.new_thread_id()
        yield {"event": "start", "data": {"thread_id": tid}}
        try:
            for node, update in workflow.stream(question, thread_id=tid):
                if node == "__end__":
                    result = update["result"]
                    self._last_results[tid] = result
                    yield {"event": "result",
                           "data": {"thread_id": tid, "result": result}}
                else:
                    yield {"event": "node", "data": {"node": node, "update": update}}
        except Exception as exc:  # noqa: BLE001 - 流转成 SSE 错误事件，不断开连接
            yield {"event": "error", "data": {"detail": f"{type(exc).__name__}: {exc}"}}

    # ------------------------------------------------------------------ 图与状态
    def graph_mermaid(self) -> dict:
        """LangGraph 状态机的 Mermaid 图（图即代码，可直接贴到支持 mermaid 的渲染器）。"""
        if self._workflow is None:
            raise LLMError(self._error or "工作流服务未初始化")
        return {
            "mermaid": self._workflow.mermaid(),
            "nodes": ["db_parser", "table_selector", "sql_generate", "sql_rewrite",
                      "sql_validate", "sql_execute", "summarize", "rewrite_router"],
        }

    def state_snapshot(self, thread_id: str) -> dict | None:
        """回查某次运行（thread_id）的状态：优先进程内注册表，其次 checkpointer。"""
        if thread_id in self._last_results:
            return {"thread_id": thread_id, "source": "last_result",
                    "result": self._last_results[thread_id]}
        workflow = self._workflow
        if workflow is not None:
            try:
                state = workflow.get_state(thread_id)
            except Exception:  # noqa: BLE001 - 未知线程等情况按不存在处理
                state = None
            if state:
                return {"thread_id": thread_id, "source": "checkpoint",
                        "state": state}
        return None

    def schema(self) -> dict:
        """返回结构化 schema（表 / 列 / 类型 / 注释 / 枚举取值 / 外键 / DDL）。"""
        from sql_agent.db import connect_readonly, parse_schema

        if self._config is None:
            raise LLMError(self._error or "服务未初始化")
        conn = connect_readonly(self._config.db.path)
        try:
            schema = parse_schema(conn)
        finally:
            conn.close()
        return {
            "tables": [
                {
                    "name": t.name,
                    "comment": t.comment,
                    "row_count": t.row_count,
                    "ddl": t.ddl,
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.type,
                            "not_null": c.not_null,
                            "primary_key": c.primary_key,
                            "comment": c.comment,
                            "distinct_values": c.distinct_values,
                        }
                        for c in t.columns
                    ],
                    "foreign_keys": [
                        {"column": fk.column, "ref_table": fk.ref_table,
                         "ref_column": fk.ref_column}
                        for fk in t.foreign_keys
                    ],
                }
                for t in schema.tables.values()
            ]
        }

    def run_batch_eval(self, ids: str | None = None) -> dict:
        """批量评测，返回指标 + 逐题明细 + Markdown 报告全文。"""
        if self._workflow is None:
            raise LLMError(self._error or "工作流服务未初始化")
        queries = select_queries(ids)  # 无匹配时抛 ValueError
        report = run_eval(self._config, self._llm, queries)
        schema = self.schema()
        ddl = "\n\n".join(t["ddl"] for t in schema["tables"])
        markdown = render_markdown(report, schema_ddl=ddl)
        report_path = write_markdown_report(report, PROJECT_ROOT / "reports",
                                            schema_ddl=ddl)
        m = report.metrics
        return {
            "started_at": report.started_at.isoformat(),
            "finished_at": report.finished_at.isoformat(),
            "provider": report.provider,
            "model": report.model,
            "max_attempts": report.max_attempts,
            "metrics": {
                "total": m.total,
                "exec_success": m.exec_success,
                "exact_match": m.exact_match,
                "loose_match": m.loose_match,
                "correct": m.correct,
                "exec_rate": round(m.exec_rate, 4),
                "correct_rate": round(m.correct_rate, 4),
                "avg_attempts": round(m.avg_attempts, 2),
                "avg_duration_ms": round(m.avg_duration_ms, 1),
                "total_tokens": m.total_tokens,
                "retried": m.retried,
                "stage_error_counts": dict(m.stage_error_counts),
            },
            "outcomes": [dataclasses.asdict(o) for o in report.outcomes],
            "markdown": markdown,
            "report_path": str(report_path),
        }


# ------------------------------------------------------------------ 单例管理
_service: WorkflowService | None = None


def init_service(config_path: str | None = None) -> WorkflowService:
    global _service
    _service = WorkflowService(config_path)
    return _service


def get_service() -> WorkflowService:
    if _service is None:
        raise RuntimeError("WorkflowService 尚未初始化")
    return _service
