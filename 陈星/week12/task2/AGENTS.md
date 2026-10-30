# AGENTS.md

## Repo state

- Implementation lives in `src/sql_agent/`; tests in `tests/`; design in `docs/agent-design.md`. `ref/` contains the fixture DB and reference notebook/demo only.
- The pipeline is implemented: **DB parsing → table selection → SQL generation → SQL validation → SQL rewrite/repair → execution → result summarization**, built with `langchain` + `langchain-openai` (`ChatOpenAI.bind_tools` for structured output).
- `src/sql_agent/llm.py` defines `StructuredAgent`: a module-level `prompt | ChatOpenAI.bind_tools(...)` chain, built lazily so importing modules and running tests never needs `OPENAI_API_KEY`. Structured output is tool-based (`json_schema` response format is unsupported on DeepSeek/DashScope) with `tool_choice="auto"`: thinking-mode models reject a forced `tool_choice` ("Thinking mode does not support this tool_choice"). Tool-call args are validated with Pydantic, with a fallback to JSON in the message body.
- Agent boundaries, data contracts, retry policy, and code layout are specified in `docs/agent-design.md`; read it before changing the workflow.
- `ref/sql-agent.ipynb` is the behavioral reference but is **incomplete**: `SQLGeneratorAgent` and `SQLResultSummaryAgent` are stubs.
- `ref/agent-demo.py` is the style reference for agents: module-level `Agent` definitions, Pydantic structured output, explicit `Workflow` class, and final JSON assembled by code rather than the model. Its `openai-agents` API is not used; the same shape is expressed with LangChain runnables.
- Do not edit `ref/` as part of normal implementation work; treat it as read-only fixture/spec. Put new code outside `ref/`.

## Environment / commands

- Python 3.12. Installed and verified: `langchain` 1.3.14, `langchain-core` 1.5.1, `langchain-openai` 1.1.9, `openai` 2.54.0, `sqlalchemy` 2.0.43, `pandas` 3.0.5, `numpy`, `tqdm`, `tabulate`, `jupyter`, `pytest`, `ruff`, `mypy`.
- Run the CLI from the repo root: `PYTHONPATH=src python3 -m sql_agent "总共有多少张专辑？"`. Requires `OPENAI_API_KEY`; `OPENAI_BASE_URL` defaults to the DeepSeek endpoint (`https://api.deepseek.com`), override it for DashScope compatible mode.
- Run tests: `pytest -q` (no API key needed; LLM calls are mocked). Lint: `ruff check src tests`.
- Logs go to stderr; the final JSON goes to stdout. Control with `--log-level DEBUG|INFO|WARNING|ERROR` or `SQL_AGENT_LOG_LEVEL`.
- Model overrides: `SQL_AGENT_MODEL` (default `deepseek-flash`) and `SQL_AGENT_SUMMARY_MODEL` (default `deepseek-flash`). `SQL_AGENT_TOOL_CHOICE` (default `auto`) controls the structured-output `tool_choice`; leave it at `auto` for thinking-mode models.
- Run the notebook: `jupyter lab ref/sql-agent.ipynb`.
- Important: the notebook hardcodes `DBParser('sqlite:///./chinook.db')`, so it only resolves when the kernel cwd is `ref/`. From the repo root the correct URL is `sqlite:///ref/chinook.db`. The docstring form `sqlite://chinook.db` is invalid for a relative path.
- Smoke-test the DB: `python -c "import sqlite3; print(sqlite3.connect('ref/chinook.db').execute('select count(*) from tracks').fetchone())"` → `(3503,)`.

## Database facts

- SQLAlchemy `inspect(engine).get_table_names()` returns 11 business tables. Raw `sqlite_master` also contains `sqlite_sequence` and `sqlite_stat1`; filter `sqlite_%` whenever querying raw SQLite metadata, or table selection may pick them.
- Tables: `albums` (347), `artists` (275), `customers` (59), `employees` (8), `genres` (25), `invoice_items` (2240), `invoices` (412), `media_types` (5), `playlist_track` (8715), `playlists` (18), `tracks` (3503).
- FK graph: `albums.ArtistId→artists`; `tracks.AlbumId→albums`, `tracks.GenreId→genres`, `tracks.MediaTypeId→media_types`; `invoice_items.InvoiceId→invoices`, `invoice_items.TrackId→tracks`; `invoices.CustomerId→customers`; `customers.SupportRepId→employees`; `employees.ReportsTo→employees` (self); `playlist_track.PlaylistId→playlists`, `playlist_track.TrackId→tracks`.
- Column names are PascalCase (`ArtistId`, `InvoiceDate`, `UnitPrice`); table names are lowercase. Use the exact casing in generated SQL and prompts.

## Reference implementation gotchas

- `DBParser.__init__` eagerly profiles **every column of every table** (distinct count, mode, NaN count, min/max, sample values) and prints each table. It takes ~0.8s on Chinook; instantiate once and reuse/cache, never per request.
- `DBParser.check_sql()` is not a dry run: it executes the SQL through `engine.begin()` (auto-commit) and returns `(ok, traceback)`. Never pass generated `INSERT/UPDATE/DELETE/DDL` to it. Validate on a read-only connection or with `EXPLAIN`.
- `DBParser.execute_sql()` returns `list[Row]` but is annotated `-> bool`. Fix the annotation in new code.
- `DBParser.get_table_sample()` returns exactly **one** row, not a representative sample.
- `get_table_fields(table).to_markdown()` depends on `tabulate` and produces the schema text sent to prompts.
- The synthetic Q/A generator (cells 16–18) is debug-limited: it uses `parser.table_names[:1]` and `break`s after the first table, retries 5×, and keeps only SQL results with exactly one row. Do not treat it as a full eval harness. `gt_qes_answer` rows are `[rewritten question, table, sql, raw result, NL answer]`.
- Cell 13 hardcodes a live DashScope API key and base URL. Never copy/reuse/commit that key; read `OPENAI_API_KEY` / `OPENAI_BASE_URL` from the environment and keep secrets out of the notebook.
- Model usage in the reference: `Agent(model="qwen-max")` for planning, `qwen-plus` for the plain `openai` helper, through the DashScope OpenAI-compatible endpoint (`https://dashscope.aliyuncs.com/compatible-mode/v1`). `Runner.run` is async. For an explicit client, pair `AsyncOpenAI` with `OpenAIChatCompletionsModel`. The current implementation reads `SQL_AGENT_MODEL` / `SQL_AGENT_SUMMARY_MODEL` (defaults in `config.py`) and `OPENAI_BASE_URL`.
- Cells 17 drive an LLM per field combination; do not execute them wholesale during routine checks (quota/time).
- Chinese is used for comments, docstrings, and prompts. Keep user-facing prompts Chinese when extending the workflow.

## Implementation constraints

- All DB access is read-only. SQLAlchemy uses `sqlite:///file:<url-encoded-abs-path>?mode=ro&uri=true`; raw `sqlite3` uses `Path.as_uri()?mode=ro`. Do not switch to a writable connection.
- `SQLValidator` must only compile with `EXPLAIN`, never execute. Safety checks run before compilation: single statement, SELECT/WITH prefix, forbidden keywords outside strings/comments.
- `src/sql_agent/agents/__init__.py` only re-exports the four module-level `StructuredAgent` instances; model wiring lives in `llm.py`. Keep `tool_choice` at `auto` when changing structured-output wiring: thinking-mode models (e.g. `deepseek-flash`) reject a forced `tool_choice` with HTTP 400 "Thinking mode does not support this tool_choice", and DashScope/DeepSeek support neither the Responses API nor the `json_schema` response format. `SQL_AGENT_TOOL_CHOICE` can be set to an output model name (e.g. `SQLDraft`) to force a specific tool on non-thinking models only.
- `ResultSummaryAgent` is skipped when the result is empty; the workflow returns a deterministic "未查询到符合条件的数据。" to avoid speculation.
- Keep comments, docstrings, prompts, and user-facing answers in Chinese to match the reference.
