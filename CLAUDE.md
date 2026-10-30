# AI Analyst Agent

LLM agent (Gemini via google-genai) that answers business questions about the
UCI Online Retail II dataset by writing read-only DuckDB SQL, with chart and
RFM tools, guardrails, tracing, and an eval suite.

## Rules
- Run everything with `uv run` (Windows, PowerShell). Add packages with `uv add`.
- Never edit `src/baseagent.py`: it is the frozen baseline for the 55-question eval.
- Never change SYSTEM_PROMPT or docs/glossary.md without asking; every change invalidates the LLM cache and needs a new version name.
- Never edit gold_sql in evals/questions.py without asking me first.
- Never read or print `.env`. Never commit `.env`, `data/` or `outputs/`.
- `outputs/traces.jsonl` and `outputs/charts/` may be read: they contain no secrets.
- Do not make Gemini API calls (running the agent, evals, or any script that imports agent_tools) unless I ask. My daily quota is small. Tests must never call the API.
- All SQL must pass validate_sql in src/guardrails.py.
- Run `uv run pytest -q` after any change. All tests must pass.
- Make small changes and explain each one. Show a plan before multi-file changes.

## Commands
- Build DB: `uv run python src/clean_and_load.py`, then `uv run python src/verify.py`
- SQL evals: `uv run python evals/run_evals.py <version> [q01,q02,...]`
- Tool evals: `uv run python evals/run_tool_evals.py <version>`
- Trace summary: `uv run python src/trace_report.py`
- API server: `uv run uvicorn --app-dir src api:app --reload` (calls Gemini on /ask)
- Run scripts from the repo root; paths like `data/retail.duckdb` are relative.

## Layout
- `src/baseagent.py`: SYSTEM_PROMPT, schema, `answer_question` (frozen SQL agent)
- `src/agent_tools.py`: tool-calling agent (`run_sql`, `make_chart`, `rfm_segments`); `_run_agent` does the work, `answer_with_tools` wraps it with trace logging
- `src/tools.py`: tool implementations; `src/guardrails.py`: sqlglot validator
- `src/tracing.py`: `SessionBudget` and `log_trace` (must not import agent_tools, baseagent or google)
- `src/trace_report.py`: summarises `outputs/traces.jsonl`
- `src/api.py`: FastAPI backend (`/health`, `/ask`, `/charts/{name}`); per-request and daily API-call budgets (MAX_DAILY_API_CALLS), optional X-API-Key (API_ACCESS_KEY); imports agent_tools lazily in `_answer`
- `evals/questions.py`: questions and gold SQL; `evals/results/*.json`: saved runs
- `docs/glossary.md`: business definitions, injected into SYSTEM_PROMPT
- `tests/`: pytest suite

## Safety
- Open the database with `read_only=True` everywhere except `clean_and_load.py`.
- Keep all three layers: prompt refusal, validate_sql, read-only connection.
  Add a test in `tests/test_guardrails.py` for any validator change.
- Traces never store result rows or tool arguments. `log_trace` must never crash the agent.
- The model name and API key come from `.env` (GEMINI_MODEL, GEMINI_API_KEY). Never hardcode them.

## Evals
- Each run gets a new version name; never overwrite an existing results file.
- Held-out batches: write the questions and gold SQL before the run, and freeze the prompt.
- After a prompt change, run the full regression and add a row to the README results table.
- When a question fails, check the gold SQL before blaming the agent.
- Evals call the live API and are rate-limited; ask before starting a full run.