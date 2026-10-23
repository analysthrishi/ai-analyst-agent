# AI Analyst Agent

An LLM agent that answers business questions about retail data by writing
and running safe SQL, choosing tools (charts, customer segmentation), and
explaining the results. Includes an evaluation suite and guardrails.

**Status:** in progress

## Dataset
UCI Online Retail II (transactions from a UK online retailer, 2009-2011).
Download it from the UCI Machine Learning Repository and place the file in
`data/raw/`. The dataset is not included in this repo.

## Setup
    uv sync
    uv run python src/clean_and_load.py
    uv run python src/verify.py

## Data cleaning
See `docs/glossary.md` for business definitions and known limitations.

## Roadmap
- [x] Data cleaning and DuckDB load
- [ ] Evaluation set (40-50 questions)
- [ ] Baseline agent
- [ ] Guardrails
- [ ] Tools (charts, RFM)
- [ ] API and UI
- [ ] Docker, CI and deployment


## Evaluation results

| Version | Score | What changed |
|---|---|---|
| baseline_v1 | 11/13 | First run (includes percent-formatting rule) |
| v2_parse_fix | 13/13 | Decline detection tolerates code fences |
| v3_guardrails | 13/13 | Added SQL validator, tests, retry loop |

Note: 13 questions is a small set. Day 5 expands it to find real weaknesses.

## Safety layers
1. Prompt tells the model to refuse destructive requests.
2. SQL validator (sqlglot) allows only a single SELECT on approved tables.
3. Read-only database connection.

| v4_batch1 | 9/13 | New questions q15-q27. 2 failures were gold-SQL issues, 2 were agent errors |
| v5_rules | 2/2 on previously failed | Rules: default to `sales`; count entities via a CTE |
| v5_regress (a+b) | 26/26 | Full regression under the new prompt, no regressions |

- Prompt rules were written after seeing failures on batch 1. Batch 2 (held-out) tests whether they generalise.

| v5_regress (a+b) | 26/26 | Full regression under the new prompt |
| v6_batch2 | 15/15 | Held-out questions written before the run; prompt frozen |

- Held-out batch is small (15 questions); a perfect score does not rule out failures on other question types.
- Result comparison accepts a match when all gold values appear in the agent's row.