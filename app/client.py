"""HTTP client for the FastAPI backend. No streamlit import, so it can be unit tested."""
import os
from dataclasses import dataclass, field, fields
from typing import Any

import requests

DEFAULT_API_URL = "http://127.0.0.1:8000"
TIMEOUT_S = 120
CHART_TIMEOUT_S = 30
MAX_ROWS = 50

# 200 statuses where the model replied but there is no data to show.
NOTE_STATUSES = {
    "refuse": "The agent declined this question.",
    "blocked": "The query was blocked by the safety checks.",
    "cannot_answer": "The agent could not answer this from the data.",
    "no_sql": "The agent replied without running a query.",
    "no_tool_result": "The agent replied without using a tool.",
}
START_API = "Start it with: uv run uvicorn --app-dir src api:app"


@dataclass
class Display:
    """Everything the UI shows for one question."""
    ok: bool
    kind: str  # success | info | warning | error
    message: str = ""
    status: str = ""
    answer: str = ""
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    chart_url: str | None = None
    caption: str = ""

    def texts(self) -> list[str]:
        """Every string the UI could render, for leak checks."""
        return [str(getattr(self, f.name)) for f in fields(self)]


def api_url() -> str:
    return (os.getenv("API_URL") or DEFAULT_API_URL).rstrip("/")


def build_headers() -> dict[str, str]:
    key = os.getenv("API_ACCESS_KEY")
    return {"X-API-Key": key} if key else {}


def build_request(question: str) -> dict:
    """Keyword arguments for requests.post."""
    return {
        "url": f"{api_url()}/ask",
        "json": {"question": question},
        "headers": build_headers(),
        "timeout": TIMEOUT_S,
    }


def _scrub(display: Display) -> Display:
    """Belt and braces: the access key never appears in anything shown."""
    key = os.getenv("API_ACCESS_KEY")
    if key:
        for f in fields(display):
            value = getattr(display, f.name)
            if isinstance(value, str) and key in value:
                setattr(display, f.name, value.replace(key, "***"))
    return display


def make_caption(body: dict) -> str:
    tools = ", ".join(t for t in body.get("tools") or [] if t) or "none"
    tokens = body.get("tokens") or {}
    return (f"Tools: {tools} · API calls: {body.get('api_calls', 0)} · "
            f"Tokens: {tokens.get('prompt', 0)} in / {tokens.get('output', 0)} out · "
            f"{float(body.get('latency_s') or 0):.1f} s")


def _chart_url(path: str | None) -> str | None:
    if not path or not path.startswith("/charts/"):
        return None  # only ever fetch charts from our own API
    return f"{api_url()}{path}"


def _detail(body: Any) -> Any:
    return body.get("detail") if isinstance(body, dict) else None


def _validation_message(body: Any) -> str:
    detail = _detail(body)
    if isinstance(detail, str):
        return detail
    msgs = []
    for item in detail if isinstance(detail, list) else []:
        if isinstance(item, dict) and item.get("msg"):
            loc = [str(p) for p in item.get("loc") or [] if p != "body"]
            msgs.append(f"{'.'.join(loc).capitalize() or 'Request'}: {item['msg']}")
    return "; ".join(msgs) or "Please check the question (3 to 500 characters)."


def to_display(status_code: int, body: Any) -> Display:
    """Turn an /ask HTTP response (already parsed JSON, or None) into a Display."""
    body = body if isinstance(body, dict) else {}
    status = body.get("status") or ""

    if status_code == 200:
        rows = body.get("rows") or []
        display = Display(
            ok=True, kind="success", status=status,
            answer=body.get("answer") or "",
            sql=body.get("sql") or "",
            columns=body.get("columns") or [],
            rows=[list(r) for r in rows[:MAX_ROWS]],
            chart_url=_chart_url(body.get("chart_url")),
            caption=make_caption(body),
        )
        if status in NOTE_STATUSES:
            display.kind, display.message = "info", NOTE_STATUSES[status]
        elif status != "ok":
            display.kind, display.message = "warning", "The agent returned an unexpected status."
        return _scrub(display)

    if status_code == 401:
        message = "This app is not authorised to use the API. Check that API_ACCESS_KEY matches the server."
    elif status_code == 422:
        message = f"The question was not accepted. {_validation_message(body)}"
    elif status_code == 429:
        detail = _detail(body)
        message = "The API-call budget has been used up. Try again later."
        if isinstance(detail, str):
            message += f" ({detail})"
    elif status_code == 502:
        message = "The language model service failed or gave no usable answer. Try again or rephrase the question."
    else:
        message = f"The server hit an unexpected error (HTTP {status_code})."

    caption = make_caption(body) if "api_calls" in body else ""
    return _scrub(Display(ok=False, kind="error", status=status, message=message, caption=caption))


def error_display(exc: Exception) -> Display:
    """Plain-language message for a failed request. Never includes str(exc)."""
    if isinstance(exc, requests.Timeout):
        message = f"The API took longer than {TIMEOUT_S} seconds to answer. Try a simpler question."
    elif isinstance(exc, requests.ConnectionError):
        message = f"Can't reach the API at {api_url()}. Is it running? {START_API}"
    else:
        message = "The request to the API failed."
    return _scrub(Display(ok=False, kind="error", message=message))


def ask(question: str) -> Display:
    try:
        resp = requests.post(**build_request(question))
    except requests.RequestException as e:
        return error_display(e)
    try:
        body = resp.json()
    except ValueError:
        body = None
    return to_display(resp.status_code, body)


def fetch_chart(chart_url: str | None) -> bytes | None:
    """PNG bytes for a chart from our API, or None on any failure."""
    if not chart_url or not chart_url.startswith(f"{api_url()}/charts/"):
        return None
    try:
        resp = requests.get(chart_url, headers=build_headers(), timeout=CHART_TIMEOUT_S)
    except requests.RequestException:
        return None
    return resp.content if resp.status_code == 200 else None
