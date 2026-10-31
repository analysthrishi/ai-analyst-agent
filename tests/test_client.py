import pytest
import requests

import client

KEY = "sekret-123"


class FakeResponse:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self.body = body
        self.content = content

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def ok_body(**overrides):
    body = {
        "status": "ok", "answer": "Total revenue is 10.", "tools": ["run_sql"],
        "sql": "SELECT 1", "columns": ["n"], "rows": [[i] for i in range(80)],
        "chart_url": "/charts/monthly_revenue.png", "api_calls": 2,
        "tokens": {"prompt": 100, "output": 20}, "latency_s": 1.5, "error": None,
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)


@pytest.fixture
def post(monkeypatch):
    """Replace requests.post; set .response or .raises, read .calls."""
    class FakePost:
        response = FakeResponse(200, ok_body())
        raises = None
        calls = []

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            if self.raises:
                raise self.raises
            return self.response

    fake = FakePost()
    fake.calls = []
    monkeypatch.setattr(client.requests, "post", fake)
    return fake


# --- building the request ---

def test_request_defaults():
    req = client.build_request("hi there")
    assert req["url"] == "http://127.0.0.1:8000/ask"
    assert req["json"] == {"question": "hi there"}
    assert req["headers"] == {}
    assert req["timeout"] == 120


def test_request_uses_env_url_and_key(monkeypatch):
    monkeypatch.setenv("API_URL", "http://example.test:9000/")
    monkeypatch.setenv("API_ACCESS_KEY", KEY)
    req = client.build_request("q?")
    assert req["url"] == "http://example.test:9000/ask"
    assert req["headers"] == {"X-API-Key": KEY}


def test_ask_sends_built_request(post):
    client.ask("total revenue")
    assert post.calls == [client.build_request("total revenue")]


# --- success ---

def test_success(post):
    d = client.ask("total revenue")
    assert d.ok and d.kind == "success" and d.message == ""
    assert d.answer == "Total revenue is 10."
    assert d.sql == "SELECT 1"
    assert d.columns == ["n"]
    assert len(d.rows) == 50
    assert d.chart_url == "http://127.0.0.1:8000/charts/monthly_revenue.png"
    assert d.caption == "Tools: run_sql · API calls: 2 · Tokens: 100 in / 20 out · 1.5 s"


def test_missing_optional_fields(post):
    post.response = FakeResponse(200, {"status": "ok"})
    d = client.ask("q?")
    assert d.ok and d.kind == "success"
    assert d.answer == "" and d.sql == ""
    assert d.rows == [] and d.columns == []
    assert d.chart_url is None
    assert d.caption == "Tools: none · API calls: 0 · Tokens: 0 in / 0 out · 0.0 s"


@pytest.mark.parametrize("status", ["refuse", "blocked", "cannot_answer", "no_sql", "no_tool_result"])
def test_model_replied_without_data(post, status):
    post.response = FakeResponse(200, ok_body(status=status, rows=None, sql=None, chart_url=None))
    d = client.ask("q?")
    assert d.ok and d.kind == "info"
    assert d.message == client.NOTE_STATUSES[status]
    assert d.answer == "Total revenue is 10."


def test_chart_url_from_elsewhere_is_ignored(post):
    post.response = FakeResponse(200, ok_body(chart_url="http://evil.test/x.png"))
    assert client.ask("q?").chart_url is None


# --- errors ---

def test_401(post):
    post.response = FakeResponse(401, {"detail": "Missing or invalid X-API-Key header."})
    d = client.ask("q?")
    assert not d.ok and d.kind == "error"
    assert "not authorised" in d.message


def test_422_shows_validation_message(post):
    post.response = FakeResponse(422, {"detail": [
        {"type": "string_too_short", "loc": ["body", "question"],
         "msg": "String should have at least 3 characters", "input": "hi"},
    ]})
    d = client.ask("hi")
    assert not d.ok
    assert d.message == "The question was not accepted. Question: String should have at least 3 characters"


def test_422_unexpected_shape(post):
    post.response = FakeResponse(422, {"detail": 42})
    assert client.ask("hi").message == (
        "The question was not accepted. Please check the question (3 to 500 characters).")


def test_429_daily_budget(post):
    post.response = FakeResponse(429, {"detail": "Daily API call budget exhausted (200/200). Try again tomorrow."})
    d = client.ask("q?")
    assert not d.ok
    assert "budget has been used up" in d.message
    assert "Daily API call budget exhausted" in d.message


def test_429_request_budget(post):
    post.response = FakeResponse(429, ok_body(status="budget_exceeded", answer=None, api_calls=8))
    d = client.ask("q?")
    assert not d.ok and d.status == "budget_exceeded"
    assert "budget has been used up" in d.message
    assert "API calls: 8" in d.caption


def test_502(post):
    post.response = FakeResponse(502, {"status": "api_error", "error": "Upstream model error."})
    d = client.ask("q?")
    assert not d.ok
    assert "language model service failed" in d.message


def test_500(post):
    post.response = FakeResponse(500, {"status": "error", "error": "Internal error."})
    d = client.ask("q?")
    assert not d.ok
    assert d.message == "The server hit an unexpected error (HTTP 500)."


def test_non_json_body(post):
    post.response = FakeResponse(503, ValueError("not json"))
    d = client.ask("q?")
    assert not d.ok
    assert d.message == "The server hit an unexpected error (HTTP 503)."


def test_timeout(post):
    post.raises = requests.Timeout("read timed out")
    d = client.ask("q?")
    assert not d.ok
    assert "longer than 120 seconds" in d.message


def test_connect_timeout_counts_as_timeout(post):
    post.raises = requests.ConnectTimeout("connect timed out")
    assert "longer than 120 seconds" in client.ask("q?").message


def test_offline(post, monkeypatch):
    monkeypatch.setenv("API_URL", "http://127.0.0.1:8123")
    post.raises = requests.ConnectionError("Max retries exceeded")
    d = client.ask("q?")
    assert not d.ok
    assert "Can't reach the API at http://127.0.0.1:8123" in d.message
    assert "uvicorn" in d.message
    assert "Max retries" not in d.message


def test_other_request_error(post):
    post.raises = requests.RequestException("boom")
    d = client.ask("q?")
    assert d.message == "The request to the API failed."


# --- the access key never reaches the screen ---

SCENARIOS = [
    FakeResponse(200, ok_body()),
    FakeResponse(200, {"status": "ok"}),
    FakeResponse(200, ok_body(status="refuse")),
    FakeResponse(401, {"detail": "Missing or invalid X-API-Key header."}),
    FakeResponse(422, {"detail": [{"loc": ["body", "question"], "msg": "too short"}]}),
    FakeResponse(429, {"detail": "Daily API call budget exhausted (200/200)."}),
    FakeResponse(429, ok_body(status="budget_exceeded")),
    FakeResponse(500, {"status": "error", "error": "Internal error."}),
    FakeResponse(502, {"status": "api_error"}),
    FakeResponse(503, ValueError("not json")),
    # even if the server somehow echoed the key back, it is masked
    FakeResponse(200, ok_body(answer=f"key is {KEY}", sql=f"-- {KEY}")),
    FakeResponse(429, {"detail": f"bad key {KEY}"}),
]
ERRORS = [
    requests.Timeout(f"timeout, headers={{'X-API-Key': '{KEY}'}}"),
    requests.ConnectionError(f"refused, X-API-Key: {KEY}"),
    requests.RequestException(KEY),
]


@pytest.mark.parametrize("scenario", SCENARIOS + ERRORS)
def test_key_never_displayed(post, monkeypatch, scenario):
    monkeypatch.setenv("API_ACCESS_KEY", KEY)
    if isinstance(scenario, Exception):
        post.raises = scenario
    else:
        post.response = scenario
    d = client.ask("q?")
    assert post.calls[0]["headers"] == {"X-API-Key": KEY}  # it is sent...
    assert not any(KEY in text for text in d.texts())  # ...but never shown


# --- charts ---

def test_fetch_chart(monkeypatch):
    monkeypatch.setenv("API_ACCESS_KEY", KEY)
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return FakeResponse(200, content=b"\x89PNG")

    monkeypatch.setattr(client.requests, "get", fake_get)
    assert client.fetch_chart("http://127.0.0.1:8000/charts/a.png") == b"\x89PNG"
    assert calls == [("http://127.0.0.1:8000/charts/a.png", {"X-API-Key": KEY}, client.CHART_TIMEOUT_S)]


def test_fetch_chart_404(monkeypatch):
    monkeypatch.setattr(client.requests, "get", lambda *a, **k: FakeResponse(404))
    assert client.fetch_chart("http://127.0.0.1:8000/charts/a.png") is None


def test_fetch_chart_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(client.requests, "get", boom)
    assert client.fetch_chart("http://127.0.0.1:8000/charts/a.png") is None


@pytest.mark.parametrize("url", [None, "", "http://evil.test/charts/a.png"])
def test_fetch_chart_refuses_other_hosts(monkeypatch, url):
    def never(*a, **k):
        raise AssertionError("should not fetch")
    monkeypatch.setattr(client.requests, "get", never)
    assert client.fetch_chart(url) is None
