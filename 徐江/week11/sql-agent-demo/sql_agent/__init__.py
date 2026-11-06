"""sql_agent —— 固定流程的 SQL Agent 工作流 Demo。

七个阶段（详见 workflow.py 中的流水线图）：

1. 数据库解析   DatabaseParserStage
2. Table 选择   TableSelectionStage
3. SQL 生成     SqlGenerationStage
4. SQL 校验     SqlValidationStage
5. SQL 改写     SqlRewriteStage（仅在校验/执行失败时触发）
6. SQL 执行     SqlExecutionStage
7. 结果汇总     ResultSummaryStage
"""

__version__ = "1.0.0"
