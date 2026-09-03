PageIndex 的核心思想是用“文档树 + LLM 推理”替代传统 RAG 的“切块 + 向量检索”。它首先根据 PDF 的目录、标题、版式和页码关系，把长文档组织成具有章节层级的树状索引，每个节点对应一个自然章节及其页码范围，并可附带摘要；对于过大的章节会继续拆分，过细的节点则会合并，以降低后续检索时的搜索和阅读成本。用户提问后，系统不计算 query 与文本块之间的 embedding 相似度，而是让 LLM 根据问题、上下文以及文档结构判断答案最可能位于哪些章节，再沿着树逐步定位到具体页面，最后读取少量原文并生成答案。

- 特点：**不用 embedding + 向量相似度来“搜 chunk”，而是先把长文档做成一棵类似目录的语义树，再让 LLM 像人翻目录一样，通过推理定位相关章节，最后只读取目标页。**
- 官方 Flash README 直接写明：基础树由 **layout statistics without an LLM** 构建，而 summary 和 retrieval-oriented refinement 才需要 LLM。
- 如果没有可靠目录，就让模型根据正文生成一个类似 TOC 的结构。代码里 `process_no_toc()` 会把页面按 token 分组，然后逐步生成 TOC；之后还会检查生成的标题到底有没有出现在对应页面。



|              | Vector RAG               | PageIndex                             |
| ------------ | ------------------------ | ------------------------------------- |
| Index        | embedding/vector         | hierarchical tree                     |
| 最小单位     | chunk                    | natural section/page                  |
| Retrieval    | similarity               | LLM reasoning                         |
| 查询依据     | query embedding          | query + conversation + domain context |
| 命中方式     | Top-K                    | 章节路由 → 定向读页                   |
| 可解释性     | “score=0.83”             | “MD&A → Margin → p73-79”              |
| DB           | Vector DB                | 不需要 Vector DB                      |
| 主要计算成本 | indexing embedding + ANN | LLM routing/read                      |

