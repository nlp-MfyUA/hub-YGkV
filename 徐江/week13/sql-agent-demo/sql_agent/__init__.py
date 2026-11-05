"""sql_agent —— 固定流程的 SQL Agent 工作流 Demo（week13 · LangGraph 框架版）。

七个阶段（详见 graph.py 中的状态机图）：

1. 数据库解析   DatabaseParserStage
2. Table 选择   TableSelectionStage     （LLM，节点内直调）
3. SQL 生成     SqlGenerationStage      （LLM，节点内直调）
4. SQL 校验     SqlValidationStage
5. SQL 改写     SqlRewriteStage         （LLM，节点内直调，仅在校验/执行失败时触发）
6. SQL 执行     SqlExecutionStage
7. 结果汇总     ResultSummaryStage      （LLM，节点内直调）

技术栈（week13 起 LangGraph 成为唯一编排框架）：
- llm.py      ChatModel 抽象（ChatOpenAI / MockChatModel，均为 BaseChatModel）
- prompts.py  ChatPromptTemplate 模板
- llm_call.py 节点内 LLM 直调（format -> invoke -> parse，取代 week12 的 LCEL 链层）
- graph.py    LangGraph StateGraph 编排（七节点 + 改写重试回路 + checkpointer）
- workflow.py 组装与驱动：run / stream（流式）/ get_state（状态回查）/ mermaid（图导出）

与 week11 / week12 的关系：阶段划分、留痕、评测指标、API/CLI 行为完全一致，
仅内部框架从「LCEL 链 + StateGraph」收敛为「LangGraph 一体」。
"""

__version__ = "3.0.0"
