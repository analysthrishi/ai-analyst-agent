from datetime import date

import pytest
from fastapi.testclient import TestClient

import api


def fake_result(**overrides):
    result = {
        "request_id": "abc123", "question": "q", "status": "ok",
        "answer": "Total revenue is 10.", "error": None,
        "tool_calls": [{"name": "run_sql", "args": {"sql": "SELECT 1"}, "ok": True}],
        "sql": "SELECT 1", "columns": ["n"], "rows": [(1,)], "chart_path": None,
        "steps": 2, "api_calls": 2, "latency_s": 1.5,
        "prompt_tokens": 100, "output_tokens": 20,
    }
    result.update(overrides)
    return result


class FakeAgent:
    """Stands in for api._answer so no Gemini call is made."""

    def __init__(self):
        self.result = fake_result()
        self.calls = []
        self.api_calls = 2
        self.raises = None

    def __call__(self, question, budget):
        self.calls.append((question, budget))
        for _ in range(self.api_calls):
            budget.add(10, 5)
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MAX_DAILY_API_CALLS", raising=False)
    monkeypatch.setattr(api, "daily", api.DailyBudget())
    monkeypatch.setattr(api, "CHART_DIR", tmp_path / "charts")


@pytest.fixture
def agent(monkeypatch):
    fake = FakeAgent()
    monkeypatch.setattr(api, "_answer", fake)
    return fake


@pytest.fixture
def client():
    return TestClient(api.app)


def ask(client, question="What is the total revenue?", **kwargs):
    return client.post("/ask", json={"question": question}, **kwargs)


# --- /health ---

def test_health(client, agent):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert agent.calls == []


# --- validation ---

@pytest.mark.parametrize("body", [
    {}, {"question": ""}, {"question": "   "}, {"question": "  a "},
    {"question": "x" * 501}, {"question": None}, {"other": "What is revenue?"},
])
def test_invalid_question_is_422(client, agent, body):
    r = client.post("/ask", json=body)
    assert r.status_code == 422
    assert agent.calls == []


def test_question_is_stripped(client, agent):
    r = ask(client, "   abc   ")
    assert r.status_code == 200
    assert agent.calls[0][0] == "abc"


def test_max_length_question_is_accepted(client, agent):
    assert ask(client, "x" * 500).status_code == 200


# --- response shape ---

def test_response_fields(client, agent):
    agent.result = fake_result(chart_path="outputs/charts/revenue_by_month.png")
    body = ask(client).json()
    assert body == {
        "status": "ok", "answer": "Total revenue is 10.", "tools": ["run_sql"],
        "sql": "SELECT 1", "columns": ["n"], "rows": [[1]],
        "chart_url": "/charts/revenue_by_month.png", "api_calls": 2,
        "tokens": {"prompt": 100, "output": 20}, "latency_s": 1.5, "error": None,
    }


def test_rows_truncated_to_50(client, agent):
    agent.result = fake_result(rows=[(i, f"r{i}") for i in range(120)])
    rows = ask(client).json()["rows"]
    assert len(rows) == 50
    assert rows[0] == [0, "r0"] and rows[-1] == [49, "r49"]


def test_no_rows_is_null(client, agent):
    agent.result = fake_result(rows=None, columns=None, sql=None)
    body = ask(client).json()
    assert body["rows"] is None and body["columns"] is None


def test_unsafe_chart_path_gives_no_url(client, agent):
    agent.result = fake_result(chart_path="outputs/charts/Bad Name.png")
    assert ask(client).json()["chart_url"] is None


# --- per-request and daily budgets ---

def test_request_budget_is_8(client, agent):
    ask(client)
    assert agent.calls[0][1].max_api_calls == 8


def test_daily_budget_exhausted_is_429_without_agent(client, agent, monkeypatch):
    monkeypatch.setenv("MAX_DAILY_API_CALLS", "0")
    r = ask(client)
    assert r.status_code == 429
    assert "Daily API call budget exhausted" in r.json()["detail"]
    assert agent.calls == []


def test_daily_budget_accumulates(client, agent, monkeypatch):
    monkeypatch.setenv("MAX_DAILY_API_CALLS", "5")
    agent.api_calls = 2
    assert ask(client).status_code == 200
    assert ask(client).status_code == 200
    assert agent.calls[1][1].max_api_calls == 3
    assert ask(client).status_code == 200
    assert agent.calls[2][1].max_api_calls == 1  # capped at what is left today
    r = ask(client)
    assert r.status_code == 429
    assert len(agent.calls) == 3


def test_daily_budget_counts_when_agent_raises(client, agent, monkeypatch):
    monkeypatch.setenv("MAX_DAILY_API_CALLS", "1")
    agent.api_calls = 1
    agent.raises = RuntimeError("boom")
    assert ask(client).status_code == 500
    assert ask(client).status_code == 429


def test_daily_budget_resets_on_new_day(client, agent, monkeypatch):
    monkeypatch.setenv("MAX_DAILY_API_CALLS", "2")
    monkeypatch.setattr(api, "_today", lambda: date(2026, 1, 1))
    assert ask(client).status_code == 200
    assert ask(client).status_code == 429
    monkeypatch.setattr(api, "_today", lambda: date(2026, 1, 2))
    assert ask(client).status_code == 200


# --- access key ---

@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_bad_key_is_401(client, agent, monkeypatch, headers):
    monkeypatch.setenv("API_ACCESS_KEY", "s3cret")
    r = ask(client, headers=headers)
    assert r.status_code == 401
    assert "s3cret" not in r.text
    assert agent.calls == []


def test_good_key_is_accepted(client, agent, monkeypatch):
    monkeypatch.setenv("API_ACCESS_KEY", "s3cret")
    assert ask(client, headers={"X-API-Key": "s3cret"}).status_code == 200


def test_no_key_configured_needs_no_header(client, agent):
    assert ask(client).status_code == 200


def test_health_needs_no_key(client, monkeypatch):
    monkeypatch.setenv("API_ACCESS_KEY", "s3cret")
    assert client.get("/health").status_code == 200


# --- charts ---

def test_chart_served(client):
    api.CHART_DIR.mkdir()
    (api.CHART_DIR / "revenue_by_month.png").write_bytes(b"\x89PNG fake")
    r = client.get("/charts/revenue_by_month.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == b"\x89PNG fake"


def test_missing_chart_is_404(client):
    assert client.get("/charts/missing.png").status_code == 404


@pytest.mark.parametrize("name", [
    "../.env", "..%2F.env", "%2e%2e%2f.env", "%2e%2e/.env", "%2e%2e",
    "..%5C.env", "A.png", "x.PNG", "x.png.txt", "sub/x.png", ".png", "x y.png",
])
def test_bad_chart_names_are_404(client, tmp_path, name):
    api.CHART_DIR.mkdir()
    (api.CHART_DIR / "x.png").write_bytes(b"png")
    (tmp_path / ".env").write_text("SECRET=1")
    r = client.get(f"/charts/{name}")
    assert r.status_code == 404
    assert "SECRET" not in r.text


# --- status mapping ---

@pytest.mark.parametrize("status, code", [
    ("ok", 200), ("refuse", 200), ("cannot_answer", 200), ("blocked", 200),
    ("no_tool_result", 200), ("no_sql", 200),
    ("budget_exceeded", 429),
    ("api_error", 502), ("empty_reply", 502), ("max_steps", 502),
    ("something_new", 500),
])
def test_status_mapping(client, agent, status, code):
    agent.result = fake_result(status=status)
    r = ask(client)
    assert r.status_code == code
    assert r.json()["status"] == status


def test_api_error_does_not_leak_provider_text(client, agent):
    agent.result = fake_result(status="api_error", error="401 key=AIzaSECRET invalid")
    r = ask(client)
    assert r.status_code == 502
    assert "AIzaSECRET" not in r.text
    assert r.json()["error"] == "Upstream model error."


def test_agent_exception_is_500_generic(client, agent):
    agent.raises = RuntimeError("key=AIzaSECRET")
    r = ask(client)
    assert r.status_code == 500
    assert "AIzaSECRET" not in r.text
    assert r.json()["error"] == "Internal error."
