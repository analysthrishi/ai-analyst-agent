import logging
import os
import re
import secrets
import threading
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, StringConstraints

from tracing import SessionBudget

load_dotenv()  # so API_ACCESS_KEY in .env is enforced before agent_tools is imported

CHART_DIR = Path("outputs/charts")  # same folder as tools.CHART_DIR
CHART_NAME = re.compile(r"[a-z0-9_]+\.png")
MAX_API_CALLS_PER_REQUEST = 8
MAX_ROWS_RETURNED = 50

# Agent status -> HTTP code. Unknown statuses get 500.
STATUS_CODES = {
    "ok": 200, "refuse": 200, "cannot_answer": 200, "blocked": 200,
    "no_tool_result": 200, "no_sql": 200,  # the model replied, just without data
    "budget_exceeded": 429,
    "api_error": 502, "empty_reply": 502, "max_steps": 502,
}

log = logging.getLogger(__name__)
app = FastAPI(title="AI Analyst Agent")


def _answer(question: str, budget: SessionBudget) -> dict:
    """Imported lazily so importing api needs no API key, model name or database."""
    from agent_tools import answer_with_tools
    return answer_with_tools(question, budget)


def _today() -> date:
    return date.today()


def _daily_limit() -> int:
    return int(os.getenv("MAX_DAILY_API_CALLS", "200"))


class DailyBudget:
    """App-wide count of API calls, reset when the date changes."""

    def __init__(self):
        self.lock = threading.Lock()
        self.day = None
        self.used = 0

    def _roll(self) -> None:
        today = _today()
        if today != self.day:
            self.day, self.used = today, 0

    def remaining(self) -> int:
        with self.lock:
            self._roll()
            return _daily_limit() - self.used

    def add(self, api_calls: int) -> None:
        with self.lock:
            self._roll()
            self.used += api_calls


daily = DailyBudget()


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class AskResponse(BaseModel):
    status: str
    answer: str | None = None
    tools: list[str] = []
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    chart_url: str | None = None
    api_calls: int = 0
    tokens: dict[str, int] = {"prompt": 0, "output": 0}
    latency_s: float = 0.0
    error: str | None = None


def _check_key(x_api_key: str | None) -> None:
    expected = os.getenv("API_ACCESS_KEY")
    if not expected:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header.")


def _chart_url(chart_path: str | None) -> str | None:
    if not chart_path:
        return None
    name = Path(chart_path).name
    return f"/charts/{name}" if CHART_NAME.fullmatch(name) else None


def _to_response(result: dict) -> AskResponse:
    rows = result.get("rows")
    status = result.get("status") or "error"
    error = result.get("error")
    if status == "api_error":
        error = "Upstream model error."  # provider error text never reaches the client
    return AskResponse(
        status=status,
        answer=result.get("answer"),
        tools=[c.get("name") for c in result.get("tool_calls") or []],
        sql=result.get("sql"),
        columns=result.get("columns"),
        rows=jsonable_encoder([list(r) for r in rows[:MAX_ROWS_RETURNED]]) if rows else rows,
        chart_url=_chart_url(result.get("chart_path")),
        api_calls=result.get("api_calls", 0),
        tokens={"prompt": result.get("prompt_tokens", 0),
                "output": result.get("output_tokens", 0)},
        latency_s=result.get("latency_s", 0.0),
        error=error,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, x_api_key: Annotated[str | None, Header()] = None):
    _check_key(x_api_key)

    remaining = daily.remaining()
    if remaining <= 0:
        limit = _daily_limit()
        raise HTTPException(
            status_code=429,
            detail=f"Daily API call budget exhausted ({limit}/{limit}). Try again tomorrow.",
        )

    budget = SessionBudget(max_api_calls=min(MAX_API_CALLS_PER_REQUEST, remaining))
    try:
        result = _answer(req.question, budget)
    except Exception as e:
        log.error("agent raised %s", type(e).__name__)
        body = AskResponse(status="error", error="Internal error.")
        return JSONResponse(status_code=500, content=body.model_dump())
    finally:
        daily.add(budget.api_calls)

    body = _to_response(result)
    code = STATUS_CODES.get(body.status, 500)
    log.info("ask: status=%s http=%d api_calls=%d", body.status, code, budget.api_calls)
    return JSONResponse(status_code=code, content=body.model_dump())


@app.get("/charts/{name}")
def chart(name: str):
    if not CHART_NAME.fullmatch(name):
        raise HTTPException(status_code=404)
    base = CHART_DIR.resolve()
    path = (base / name).resolve()
    if path.parent != base or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png")
