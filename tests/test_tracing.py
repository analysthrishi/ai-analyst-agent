import json

import pytest

import tracing
from trace_report import build_report, load_traces
from tracing import SessionBudget, estimate_cost, log_trace


@pytest.fixture
def trace_file(tmp_path, monkeypatch):
    path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACE_PATH", path)
    return path


@pytest.fixture
def prices(monkeypatch):
    monkeypatch.setattr(tracing, "PRICE_PER_M_INPUT", 1.0)
    monkeypatch.setattr(tracing, "PRICE_PER_M_OUTPUT", 4.0)


def sample_result(**overrides):
    result = {
        "request_id": "abc123", "question": "What is the total revenue?",
        "status": "ok", "answer": "Total revenue is 10.", "error": None,
        "tool_calls": [{"name": "run_sql", "args": {"sql": "SELECT 1"}, "ok": True}],
        "sql": "SELECT SUM(revenue) FROM sales", "rows": [("SECRET_ROW", 10)],
        "chart_path": None, "steps": 2, "api_calls": 2,
        "latency_s": 1.5, "prompt_tokens": 1000, "output_tokens": 200,
    }
    result.update(overrides)
    return result


# --- estimate_cost ---

def test_cost_is_zero_when_prices_are_zero(monkeypatch):
    monkeypatch.setattr(tracing, "PRICE_PER_M_INPUT", 0.0)
    monkeypatch.setattr(tracing, "PRICE_PER_M_OUTPUT", 0.0)
    assert estimate_cost(1_000_000, 1_000_000) == 0.0

def test_cost_uses_prices(prices):
    assert estimate_cost(1_000_000, 500_000) == pytest.approx(1.0 + 2.0)


# --- SessionBudget ---

def test_budget_starts_not_exceeded():
    budget = SessionBudget()
    assert not budget.exceeded()
    assert budget.reason() is None


def test_budget_api_call_limit():
    budget = SessionBudget(max_api_calls=2)
    budget.add(10, 5)
    assert not budget.exceeded()
    budget.add(10, 5)
    assert budget.exceeded()
    assert "API call limit" in budget.reason()


def test_budget_token_limit_counts_input_and_output():
    budget = SessionBudget(max_api_calls=None, max_tokens=100)
    budget.add(60, 30)
    assert not budget.exceeded()
    budget.add(5, 5)
    assert budget.exceeded()
    assert "Token limit" in budget.reason()


def test_budget_cost_limit(prices):
    budget = SessionBudget(max_api_calls=None, max_cost_usd=0.01)
    budget.add(5_000, 0)  # $0.005
    assert not budget.exceeded()
    budget.add(5_000, 0)  # $0.010 total
    assert budget.exceeded()
    assert "Cost limit" in budget.reason()


def test_budget_none_limits_are_ignored():
    budget = SessionBudget(max_api_calls=None, max_tokens=None, max_cost_usd=None)
    for _ in range(100):
        budget.add(1_000_000, 1_000_000)
    assert not budget.exceeded()


def test_budget_summary(prices):
    budget = SessionBudget(max_api_calls=5, max_tokens=1000)
    budget.add(100, 50)
    summary = budget.summary()
    assert summary["api_calls"] == 1
    assert summary["max_api_calls"] == 5
    assert summary["prompt_tokens"] == 100
    assert summary["output_tokens"] == 50
    assert summary["max_tokens"] == 1000
    assert summary["cost_usd"] == pytest.approx(0.0003)


# --- log_trace ---

def test_log_trace_writes_valid_line(trace_file, prices):
    log_trace(sample_result())
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record) == {
        "time", "request_id", "question", "status", "tools", "steps", "api_calls",
        "prompt_tokens", "output_tokens", "latency_s", "est_cost_usd",
        "sql", "chart_path", "error",
    }
    assert record["status"] == "ok"
    assert record["tools"] == ["run_sql"]
    assert record["est_cost_usd"] == pytest.approx(0.0018)


def test_log_trace_appends(trace_file):
    log_trace(sample_result(question="q1"))
    log_trace(sample_result(question="q2"))
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["question"] for line in lines] == ["q1", "q2"]


def test_log_trace_never_stores_rows(trace_file):
    log_trace(sample_result())
    text = trace_file.read_text(encoding="utf-8")
    assert "SECRET_ROW" not in text
    assert "rows" not in json.loads(text)


def test_log_trace_creates_folder(tmp_path, monkeypatch):
    path = tmp_path / "new" / "dir" / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACE_PATH", path)
    log_trace(sample_result())
    assert path.exists()


def test_log_trace_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACE_PATH", tmp_path)  # a directory: cannot append
    log_trace(sample_result())  # must not raise
    log_trace({})  # nearly empty result must not raise either


# --- trace_report ---

def test_report_counts_and_averages(trace_file):
    log_trace(sample_result(status="ok", api_calls=2, latency_s=1.0))
    log_trace(sample_result(status="refuse", tool_calls=[], api_calls=1, latency_s=3.0))
    with trace_file.open("a", encoding="utf-8") as f:
        f.write("not json\n\n")  # broken and blank lines are skipped
    records = load_traces(trace_file)
    report = build_report(records)
    assert len(records) == 2
    assert "Runs: 2" in report
    assert "ok: 1" in report
    assert "refuse: 1" in report
    assert "run_sql: 1" in report
    assert "API calls:     1.50" in report
    assert "Latency:       2.00s" in report


def test_report_with_no_records():
    assert build_report([]) == "No traces yet."

def test_cost_math_with_known_prices(monkeypatch):
    monkeypatch.setattr(tracing, "PRICE_PER_M_INPUT", 0.30)
    monkeypatch.setattr(tracing, "PRICE_PER_M_OUTPUT", 2.50)
    assert estimate_cost(1_000_000, 1_000_000) == 2.8
    assert estimate_cost(1000, 500) == 0.00155