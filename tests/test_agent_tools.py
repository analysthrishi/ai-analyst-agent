import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

import tracing
from tracing import SessionBudget

# baseagent reads the database and these env vars at import time, so agent_tools
# is imported lazily (in the fixture below) and the module is skipped without them.
load_dotenv()
DB_PATH = Path("data/retail.duckdb")
MISSING = ([] if DB_PATH.exists() else [str(DB_PATH)]) + [
    name for name in ("GEMINI_API_KEY", "GEMINI_MODEL") if not os.getenv(name)
]
pytestmark = pytest.mark.skipif(
    bool(MISSING), reason=f"baseagent needs at import: {', '.join(MISSING)} (missing)"
)


def text_reply(text):
    part = SimpleNamespace(text=text, function_call=None)
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5),
    )


def tool_reply(name):
    call = SimpleNamespace(name=name, args={})
    part = SimpleNamespace(text=None, function_call=call)
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5),
    )


class FakeClient:
    """Stands in for base.client so no Gemini call is made."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.models = self

    def generate_content(self, **kwargs):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture(autouse=True)
def trace_file(tmp_path, monkeypatch):
    """Keep test runs out of the real outputs/traces.jsonl."""
    path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACE_PATH", path)
    return path


@pytest.fixture
def agent_tools():
    import agent_tools
    return agent_tools


@pytest.fixture
def answer_with_tools(agent_tools):
    return agent_tools.answer_with_tools


@pytest.fixture
def fake(monkeypatch, agent_tools):
    def install(*replies):
        client = FakeClient(replies)
        monkeypatch.setattr(agent_tools.base, "client", client)
        return client
    return install


def test_no_budget_behaves_as_before(fake, answer_with_tools):
    client = fake(text_reply("Done."))
    out = answer_with_tools("q")
    assert out["status"] == "no_tool_result"
    assert out["api_calls"] == 1
    assert client.calls == 1
    assert out["request_id"]


def test_budget_stops_mid_question(fake, answer_with_tools):
    # "nope" is an unknown tool, so no database is needed.
    client = fake(tool_reply("nope"), text_reply("Done."))
    budget = SessionBudget(max_api_calls=1)
    out = answer_with_tools("q", budget)
    assert out["status"] == "budget_exceeded"
    assert "API call limit" in out["error"]
    assert client.calls == 1
    assert budget.api_calls == 1


def test_budget_spans_questions(fake, answer_with_tools):
    client = fake(text_reply("a"), text_reply("b"), text_reply("c"))
    budget = SessionBudget(max_api_calls=2)
    assert answer_with_tools("q1", budget)["status"] == "no_tool_result"
    assert answer_with_tools("q2", budget)["status"] == "no_tool_result"
    out = answer_with_tools("q3", budget)
    assert out["status"] == "budget_exceeded"
    assert out["api_calls"] == 0
    assert client.calls == 2


def test_budget_gets_token_counts(fake, answer_with_tools):
    fake(tool_reply("nope"), text_reply("Done."))
    budget = SessionBudget()
    answer_with_tools("q", budget)
    assert budget.prompt_tokens == 20
    assert budget.output_tokens == 10


def test_budget_token_limit_stops_agent(fake, answer_with_tools):
    client = fake(tool_reply("nope"), text_reply("Done."))
    budget = SessionBudget(max_tokens=15)
    out = answer_with_tools("q", budget)
    assert out["status"] == "budget_exceeded"
    assert "Token limit" in out["error"]
    assert client.calls == 1


def test_failed_call_counts_toward_budget(fake, answer_with_tools):
    fake(RuntimeError("quota"))
    budget = SessionBudget(max_api_calls=5)
    out = answer_with_tools("q", budget)
    assert out["status"] == "api_error"
    assert out["api_calls"] == 0
    assert budget.api_calls == 1


def test_each_run_writes_one_trace(fake, trace_file, answer_with_tools):
    fake(text_reply("a"), text_reply("b"))
    answer_with_tools("q1")
    answer_with_tools("q2")
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["question"] for line in lines] == ["q1", "q2"]


def test_run_sql_stores_columns(monkeypatch, agent_tools):
    monkeypatch.setattr(agent_tools.base, "run_sql", lambda sql: (["a"], [(1,)]))
    state = {"sql": None, "columns": None, "rows": None, "chart_path": None,
             "blocked": None, "succeeded": False}
    out = agent_tools.execute_tool("run_sql", {"sql": "SELECT 1 AS a"}, state)
    assert out["ok"]
    assert state["columns"] == ["a"]
    assert state["rows"] == [(1,)]


def test_request_is_logged(fake, caplog, answer_with_tools):
    fake(tool_reply("nope"), text_reply("Done."))
    with caplog.at_level(logging.DEBUG, logger="agent_tools"):
        out = answer_with_tools("q")
    messages = [r.getMessage() for r in caplog.records]
    rid = out["request_id"]
    assert any(m.startswith(f"request {rid} done: status=no_tool_result") for m in messages)
    assert any(f"request {rid} tool nope ok=False" in m for m in messages)
    assert sum(f"request {rid} step" in m for m in messages) == 2
