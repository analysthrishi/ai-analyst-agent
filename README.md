# AI Analyst Agent

An LLM agent (Gemini via `google-genai`) that answers business questions about
retail data. It writes read-only DuckDB SQL, calls tools for charts and customer
segmentation, and explains the results. It ships with guardrails, request
tracing, a 55-question eval suite, an API, a UI, Docker and CI.

**Status:** complete. The latest full run (`v13_after_fix`) scores 55/55.

## Dataset
UCI Online Retail II: transactions from a UK online retailer, 2009-2011.
Download it from the UCI Machine Learning Repository and place the file in
`data/raw/`. The dataset is not included in this repo.

Business definitions (revenue, valid sale, order, etc.) and known cleaning
limitations are in [`docs/glossary.md`](docs/glossary.md). The glossary is
injected into the system prompt.

## How it works
- **SQL agent** (`src/baseagent.py`): frozen baseline. System prompt, schema and
  `answer_question`. It is not edited, so the 55-question eval stays comparable.
- **Tool agent** (`src/agent_tools.py`): adds three tools: `run_sql`, `make_chart`
  and `rfm_segments` (implementations in `src/tools.py`).
- **Guardrails** (`src/guardrails.py`): a sqlglot validator.
- **Tracing** (`src/tracing.py`, `src/trace_report.py`): per-request traces go to
  `outputs/traces.jsonl`. They never store result rows or raw tool-call arguments; the validated SQL is kept for debugging.
- **API** (`src/api.py`): FastAPI with `/health`, `/ask` and `/charts/{name}`,
  per-request and daily API-call budgets, and an optional `X-API-Key`.
- **UI** (`app/streamlit_app.py`): Streamlit front end over `app/client.py`.

## Safety layers
1. The prompt tells the model to refuse destructive or unanswerable requests.
2. The SQL validator allows only a single SELECT on approved tables. It
   normalises invisible characters before parsing.
3. The database connection is read-only.

## Setup
Create a `.env` file in the repo root with `GEMINI_API_KEY` and `GEMINI_MODEL`
(never commit it), then:

    uv sync
    uv run python src/clean_and_load.py
    uv run python src/verify.py

## Usage
    uv run pytest -q                                   # tests, no API calls
    uv run uvicorn --app-dir src api:app --reload      # API on :8000 (calls Gemini)
    uv run streamlit run app/streamlit_app.py          # UI (start the API first)
    docker compose up --build                          # API :8000, UI :8501

`API_URL` (default `http://127.0.0.1:8000`) and `API_ACCESS_KEY` can be set in
the environment for the UI. Build the database before using Docker, since it is
mounted read-only.

## Evaluation
Questions and gold SQL are in `evals/questions.py`. Saved runs are in
`evals/results/`. A result counts as a match when all gold values appear in the
agent's row, so a perfect score does not rule out failures on other question types.

Run: `uv run python evals/run_evals.py <version> [q01,q02,...]`. It calls the
live API and is rate-limited, so use sparingly. Each run needs a new version name.

### Results
| Version | Score | What changed |
|---|---|---|
| baseline | 11/13 | First run. Failed q04 (month formatting) and q08 (top-10% share) |
| baseline_v1 | 12/13 | Added percent-formatting rule. q08 still failing |
| v2_parse_fix | 13/13 | Decline detection tolerates code fences |
| v3_guardrails | 13/13 | Added SQL validator, tests, retry loop |
| v4_batch1 | 9/13 | New questions q15-q27. Two failures were gold-SQL issues (q19, q21), two were agent errors (q15, q24) |
| v4_batch1_regold | 2/2 | Re-ran q19 and q21 after fixing their gold SQL |
| v5_rules | 2/2 | Rules: default to `sales`; count entities via a CTE. Re-ran q15 and q24 |
| v5_regress (a+b) | 26/26 | Full regression under the new prompt, no regressions |
| v6_batch2 | 15/15 | Held-out questions written before the run; prompt frozen |
| v7_batch3 | 5/8 | Failed q43 (LAG after filter), q48 (rank before grouping), q50 (undefined "order") |
| v8_fixes | 3/3 | Window rule, top-N rule, glossary definition of "order" |
| v8_regress (a+b+c) | 47/48 | Full regression. q30 was blocked by the validator (see below) |
| v9_fresh | 3/4 | Generalisation test: window 1/1, top-N 2/2, order definition 0/1 (q53, near miss: 83.63 vs 83.66 days) |
| v10_order | 3/3 | Rule: orders are identified by invoice, plus fresh order questions |
| v10_regress (a+b+c) | 53/53 | Full regression under the near-final prompt |
| v11_final (a+b+c) | 53/53 | Final-prompt regression |
| v12_validator_fix | 55/55 | First single full run of all 55 questions, after the validator fix |
| v13_after_fix | 55/55 | Full run, 55 questions |
| v14_glossary_fmt | 3/3 | Spot-check (q30, q50, q53) after the glossary reformat (order and quirk bullets moved into the main list; wording unchanged) and the validator scope fix. Not a full run |
| tools_v1 / tools_v2 | 10/10, 10/10 | Tool evals (`evals/run_tool_evals.py`) |

Notes:
- Prompt rules were written after seeing failures on batch 1. Batch 2 was held
  out to test whether they generalise (15/15). Batch 3 then exposed three new
  failure types, which v8 and v10 addressed.
- When a question failed, the gold SQL was checked before blaming the agent.
  Two of the four batch 1 failures were gold errors.

### Failure analysis
A regression run caught the validator rejecting a harmless question (q30). The
model's SQL contained an invisible zero-width space. I added a failing test,
normalised invisible characters before parsing, and verified that obfuscated
attacks are still blocked.

More entries are in [`docs/failure_note.md`](docs/failure_note.md).

## Deployment
The app is two services. Streamlit Community Cloud runs Python scripts from a GitHub
repo and does not use Dockerfiles, so the Docker image is for the API host only.
  
| Part | Where | Files |
|---|---|---|
| API (FastAPI + DuckDB + Gemini) | Render (Docker web service, builds from GitHub) | `Dockerfile.render` |
| UI (Streamlit) | Streamlit Community Cloud | `app/streamlit_app.py`, `app/requirements.txt` |

`Dockerfile.render` downloads `retail.duckdb` at build time from a GitHub Release
(tag `data-v1`), so the database never enters git. Build the database locally with
`uv run python src/clean_and_load.py`, then attach `data/retail.duckdb` to that release.

**API (Render):** New Web Service, connect this repo, language Docker, Dockerfile path
`./Dockerfile.render`, health check path `/health`. Environment variables:
`GEMINI_API_KEY`, `GEMINI_MODEL`, `API_ACCESS_KEY` (a long random string; without it the
API is open) and `MAX_DAILY_API_CALLS` (for example 20). Also set a spend or quota limit on the Gemini key.

**UI (Streamlit Community Cloud):** new app from this repo, branch `main`, main file
`app/streamlit_app.py`, Python 3.13. In Secrets:

    API_URL = "https://<your-service>.onrender.com"
    API_ACCESS_KEY = "<same value as on Render>"

Limits to know about:
- The daily call budget is held in memory, so it resets when the API restarts or wakes from idle.
- Free Render services sleep when idle; the first request after that takes about a minute.
- Charts and traces are on ephemeral disk and are lost on restart.
- Each browser session may ask 10 questions (`MAX_QUESTIONS_PER_SESSION` to change). This is a
  speed bump, not security: reloading the page starts a new session. The real cap is `MAX_DAILY_API_CALLS`.

## CI and deployment
GitHub Actions (`.github/workflows/ci.yml`) runs `uv sync --locked` and
`uv run pytest -q` on push and PR to `main`. It uses no secrets, no `data/` and
makes no Gemini calls. The `Dockerfile` builds a non-root image that runs
uvicorn on port 8000 (used by `docker compose`).
