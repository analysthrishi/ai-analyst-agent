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