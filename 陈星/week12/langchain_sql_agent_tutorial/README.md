# LangChain SQL Agent：从 OpenAI Agents 作业到教学版复刻

这是按上传的 `week12/task2` 作业组织的**教学复刻**，数据库沿用原作业 Chinook。

## 学习顺序

1. `step1_read_db.py`：先不用 AI，用 Python 检查数据库能不能查。
2. `step2_structured_output.py`：只实现一个“选表 Agent”，观察 `prompt | llm.bind_tools()`。
3. `sql_agent_langchain.py`：加入 4 个专职 Agent、SQL 校验、有限重试和结果总结。
4. `test_db_tools.py`：用无需 API 的单元测试验证安全边界。

## 安装

需要 Python 3.10+，建议 3.11 或 3.12。

```bash
cd langchain_sql_agent_tutorial
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填入自己合法的 API Key。
注意：作业原 Notebook 中的硬编码密钥不要复制进项目，如仍有效应及时更换。

## 运行顺序

```bash
python step1_read_db.py
python -m unittest -v test_db_tools.py
python step2_structured_output.py
python sql_agent_langchain.py "总共有多少张专辑？"
python sql_agent_langchain.py "哪位歌手拥有最多专辑？"
python sql_agent_langchain.py "购买金额最高的 5 位客户是谁？"
```

### 预期情况

- `step1_read_db.py` 不联网，正确打印专辑数 `347`。
- 单元测试不联网，能发现非法 SQL 并确认数据库只读。
- `step2_structured_output.py` 和完整 Agent 要联网、有 API Key、并且模型支持 OpenAI-compatible tool calling。
- 模型结果具有不确定性，所以 **不能保证每次都能一次选对表或写对 SQL**；失败时会进入有限的修复流程。

## OpenAI Agents 与 LangChain 对照

| 原写法 | 本项目写法 |
| --- | --- |
| `Agent(name=..., instructions=..., output_type=...)` | `ChatPromptTemplate` + `ChatOpenAI.bind_tools([Pydantic模型])` |
| `Runner.run(agent, input)` | `chain.invoke({"data": input})` |
| `result.final_output` | `AIMessage.tool_calls[0]["args"]` 后用 Pydantic 校验 |
| `@function_tool` | 工具可用 `@tool`；本作业采用独立 Python SQL 工具，避免让 LLM 自行执行 SQL |
| `Workflow` 编排 | `LangChainSQLAgent.run()` 用 Python 控制步骤和修复次数 |

## 为什么不直接使用通用 `create_sql_agent`？

这是一个为了教学而设计的**可控工作流**。选表、写 SQL、修复、总结都有清晰的数据契约；执行数据库的权限始终在 Python 代码手里。它刻意不把 SQL 执行工具交给模型随意调用。LangChain 也提供现成 SQL Agent / Toolkit，但它们并不等于原作业的显式四 Agent 流程。

## 工程边界

- 只面向本地 SQLite `chinook.db`；不是完整数据库防火墙。
- `validate()` 采用关键字检查 + SQLite EXPLAIN，实际读写限制依赖 SQLite `mode=ro` / `query_only`。
- 有 5 秒 SQLite progress handler 期限，以及最多 200 行输出限制。
- `shown_rows` 是取出展示的行数，不代表数据库真实结果总数。
- 面向生产使用时，需增加 SQL AST 校验、隔离账户、监控、权限表白名单以及更完整的异常分类和测试。
