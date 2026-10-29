"""sql_agent —— 固定流程的 SQL Agent 工作流 Demo（LangChain 架构版）。

七个阶段（详见 graph.py 中的状态机图）：

1. 数据库解析   DatabaseParserStage
2. Table 选择   TableSelectionStage     （LCEL 链）
3. SQL 生成     SqlGenerationStage      （LCEL 链）
4. SQL 校验     SqlValidationStage
5. SQL 改写     SqlRewriteStage         （LCEL 链，仅在校验/执行失败时触发）
6. SQL 执行     SqlExecutionStage
7. 结果汇总     ResultSummaryStage      （LCEL 链）

LangChain 分层：
- llm.py     ChatModel 抽象（ChatOpenAI / MockChatModel，均为 BaseChatModel）
- prompts.py ChatPromptTemplate 模板
- chains.py  LCEL 链（prompt | model | parser）
- graph.py   LangGraph StateGraph 编排（七节点 + 改写重试回路）
"""

__version__ = "2.0.0"
