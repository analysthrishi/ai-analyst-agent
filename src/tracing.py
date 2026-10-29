import json
import logging
from datetime import datetime
from pathlib import Path

TRACE_PATH = Path("outputs/traces.jsonl")

# USD per 1M tokens. Placeholders: fill in the real Gemini prices for your model.
PRICE_PER_M_INPUT = 0.30
PRICE_PER_M_OUTPUT = 2.50

log = logging.getLogger(__name__)


def estimate_cost(prompt_tokens: int, output_tokens: int) -> float:
    return (prompt_tokens / 1_000_000 * PRICE_PER_M_INPUT
            + output_tokens / 1_000_000 * PRICE_PER_M_OUTPUT)


class SessionBudget:
    """Limits for one session. A limit of None is not checked."""

    def __init__(self, max_api_calls=30, max_tokens=None, max_cost_usd=None):
        self.max_api_calls = max_api_calls
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.api_calls = 0
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def add(self, prompt_tokens: int = 0, output_tokens: int = 0) -> None:
        """Record one API call and its token usage."""
        self.api_calls += 1
        self.prompt_tokens += prompt_tokens
        self.output_tokens += output_tokens
        self.cost_usd += estimate_cost(prompt_tokens, output_tokens)

    def reason(self) -> str | None:
        if self.max_api_calls is not None and self.api_calls >= self.max_api_calls:
            return f"API call limit reached ({self.api_calls}/{self.max_api_calls})."
        tokens = self.prompt_tokens + self.output_tokens
        if self.max_tokens is not None and tokens >= self.max_tokens:
            return f"Token limit reached ({tokens}/{self.max_tokens})."
        if self.max_cost_usd is not None and self.cost_usd >= self.max_cost_usd:
            return f"Cost limit reached (${self.cost_usd:.4f}/${self.max_cost_usd:.4f})."
        return None

    def exceeded(self) -> bool:
        return self.reason() is not None

    def summary(self) -> dict:
        return {
            "api_calls": self.api_calls, "max_api_calls": self.max_api_calls,
            "prompt_tokens": self.prompt_tokens, "output_tokens": self.output_tokens,
            "max_tokens": self.max_tokens,
            "cost_usd": round(self.cost_usd, 6), "max_cost_usd": self.max_cost_usd,
        }


def log_trace(result: dict) -> None:
    """Append one JSON line for a run. Never stores rows and never raises."""
    try:
        prompt_tokens = result.get("prompt_tokens", 0) or 0
        output_tokens = result.get("output_tokens", 0) or 0
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "request_id": result.get("request_id"),
            "question": result.get("question"),
            "status": result.get("status"),
            "tools": [c.get("name") for c in result.get("tool_calls") or []],
            "steps": result.get("steps", 0),
            "api_calls": result.get("api_calls", 0),
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "latency_s": result.get("latency_s", 0.0),
            "est_cost_usd": round(estimate_cost(prompt_tokens, output_tokens), 6),
            "sql": result.get("sql"),
            "chart_path": result.get("chart_path"),
            "error": result.get("error"),
        }
        path = Path(TRACE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("Could not write trace: %s", e)
