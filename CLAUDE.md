# AI Analyst Agent

LLM agent (Gemini via google-genai) that answers business questions about the
UCI Online Retail II dataset by writing read-only DuckDB SQL, with chart and
RFM tools, guardrails, and an eval suite.

## Rules
- Run everything with `uv run` (Windows, PowerShell). Add packages with `uv add`.
- Never edit `src/baseagent.py`: it is the frozen baseline for the 55-question eval.
- Never change SYSTEM_PROMPT or docs/glossary.md without asking; every change invalidates the LLM cache and needs a new version name.
- Never edit gold_sql in evals/questions.py without asking me first.
- Never read, print or commit .env, data/ or outputs/.
- All SQL must pass validate_sql in src/guardrails.py.
- Run `uv run pytest -q` after any change. Currently 73 tests pass.
- Make small changes and explain each one.

## Commands
- Build DB: `uv run python src/clean_and_load.py`, then `uv run python src/verify.py`
- SQL evals: `uv run python evals/run_evals.py <version> [q01,q02,...]`
- Tool evals: `uv run python evals/run_tool_evals.py <version>`
- Run scripts from the repo root; paths like `data/retail.duckdb` are relative.

## Layout
- `src/baseagent.py`: SYSTEM_PROMPT, schema, `answer_question` (frozen SQL agent)
- `src/agent_tools.py`: tool-calling agent (`run_sql`, `make_chart`, `rfm_segments`)
- `src/tools.py`: tool implementations; `src/guardrails.py`: sqlglot validator
- `evals/questions.py`: questions and gold SQL; `evals/results/*.json`: saved runs
- `docs/glossary.md`: business definitions, injected into SYSTEM_PROMPT

## Safety
- Open the database with `read_only=True` everywhere except `clean_and_load.py`.
- Keep all three layers: prompt refusal, validate_sql, read-only connection.
  Add a test in `tests/test_guardrails.py` for any validator change.

## Evals
- Each run gets a new version name; never overwrite an existing results file.
- Held-out batches: write the questions and gold SQL before the run, and freeze the prompt.
- After a prompt change, run the full regression and add a row to the README results table.
- When a question fails, check the gold SQL before blaming the agent.
- Evals call the live API and are rate-limited; ask before starting a full run.
