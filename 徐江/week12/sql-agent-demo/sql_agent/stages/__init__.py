"""七个 Stage 的实现，一个模块对应工作流中的一个环节。

week12 起四个 LLM stage（table_selector / sql_generator / sql_rewriter /
summarizer）内部改走 LCEL 链（见 chains.py），其余三个纯本地 stage 不变。
"""
