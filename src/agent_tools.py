import json
import time

from google.genai import types

import baseagent as base
import tools as tool_impl
from guardrails import validate_sql

MAX_STEPS = 6
MAX_ROWS_TO_MODEL = 50

TOOL_ADDENDUM = """

TOOL MODE (this section overrides the reply-format rules above):
- You have three tools: run_sql, make_chart, rfm_segments. Call a tool instead of replying with a ```sql block.
- Use run_sql for questions answered with numbers or tables. All the SQL rules above still apply.
- Use make_chart ONLY when the user asks for a chart, plot, graph or visual.
- Use rfm_segments ONLY when the user asks for customer segments, segmentation or RFM.
- Never call a tool you do not need. One tool is usually enough.
- After tool results come back, answer in 2-3 plain sentences using only numbers the tools returned. If a chart was saved, mention its file path.
- If a tool returns ok=false, correct the problem and try once more. If the error says 'Blocked by guardrails', do not try again.
- If the request asks to modify or delete data, reply with text starting with REFUSE: and a reason. If the data cannot answer the question, reply with text starting with CANNOT_ANSWER: and a reason. Do not call any tool in either case.
"""

TOOL_PROMPT = base.SYSTEM_PROMPT + TOOL_ADDENDUM

TOOL_DECLARATIONS = [
    {
        "name": "run_sql",
        "description": "Run one read-only DuckDB SELECT query on the retail data and return the rows.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT statement."},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "make_chart",
        "description": (
            "Run a SELECT query and save the result as a bar or line chart (PNG). "
            "The query result must contain the columns named in x and y."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT statement."},
                "kind": {"type": "string", "enum": ["bar", "line"]},
                "x": {"type": "string", "description": "Column for the x axis."},
                "y": {"type": "string", "description": "Numeric column for the y axis."},
                "title": {"type": "string", "description": "Chart title."},
            },
            "required": ["sql", "kind", "x", "y", "title"],
        },
    },
    {
        "name": "rfm_segments",
        "description": (
            "Segment all identified customers by recency, frequency and monetary value "
            "and return a summary per segment. Takes no arguments."
        ),
    },
]


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def execute_tool(name: str, args: dict, state: dict) -> dict:
    if name == "run_sql":
        ok, reason, safe_sql = validate_sql(args.get("sql", ""))
        if not ok:
            state["blocked"] = reason
            return {"ok": False, "error": f"Blocked by guardrails: {reason}"}
        try:
            columns, rows = base.run_sql(safe_sql)
        except Exception as e:
            return {"ok": False, "error": f"SQL failed: {e}"}
        state.update(sql=safe_sql, rows=rows, succeeded=True)
        return _jsonable({
            "ok": True, "columns": columns, "row_count": len(rows),
            "rows": [list(r) for r in rows[:MAX_ROWS_TO_MODEL]],
        })

    if name == "make_chart":
        out = tool_impl.make_chart(
            sql=args.get("sql", ""), kind=args.get("kind", ""),
            x=args.get("x", ""), y=args.get("y", ""), title=args.get("title", "chart"),
        )
        if out.get("ok"):
            state.update(chart_path=out["path"], succeeded=True)
        elif "Blocked" in out.get("error", ""):
            state["blocked"] = out["error"]
        return _jsonable(out)

    if name == "rfm_segments":
        out = tool_impl.rfm_segments()
        state["succeeded"] = True
        return _jsonable(out)

    return {"ok": False, "error": f"Unknown tool: {name}"}


def answer_with_tools(question: str) -> dict:
    state = {"sql": None, "rows": None, "chart_path": None,
             "blocked": None, "succeeded": False}
    result = {
        "question": question, "status": None, "answer": None, "error": None,
        "tool_calls": [], "sql": None, "rows": None, "chart_path": None,
        "steps": 0, "api_calls": 0,
        "latency_s": 0.0, "prompt_tokens": 0, "output_tokens": 0,
    }

    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    config = types.GenerateContentConfig(
        system_instruction=TOOL_PROMPT,
        temperature=0,
        tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    for step in range(MAX_STEPS):
        result["steps"] = step + 1
        start = time.time()
        try:
            resp = base.client.models.generate_content(
                model=base.MODEL, contents=contents, config=config
            )
        except Exception as e:
            result.update(status="api_error", error=str(e))
            return result

        result["api_calls"] += 1
        result["latency_s"] = round(result["latency_s"] + (time.time() - start), 2)
        usage = getattr(resp, "usage_metadata", None)
        result["prompt_tokens"] += getattr(usage, "prompt_token_count", 0) or 0
        result["output_tokens"] += getattr(usage, "candidates_token_count", 0) or 0

        if not resp.candidates or not resp.candidates[0].content:
            result.update(status="empty_reply", error="Model returned no content.")
            return result

        model_content = resp.candidates[0].content
        calls = [p.function_call for p in (model_content.parts or [])
                 if getattr(p, "function_call", None)]

        if not calls:
            text = "".join(p.text for p in (model_content.parts or [])
                           if getattr(p, "text", None)).strip()
            result["answer"] = text
            decline = base.detect_decline(text)
            if decline:
                result["status"] = decline
            elif state["succeeded"]:
                result["status"] = "ok"
            elif state["blocked"]:
                result.update(status="blocked", error=state["blocked"])
            else:
                result["status"] = "no_tool_result"
            result.update(sql=state["sql"], rows=state["rows"], chart_path=state["chart_path"])
            return result

        contents.append(model_content)
        response_parts = []
        for fc in calls:
            args = dict(fc.args) if fc.args else {}
            out = execute_tool(fc.name, args, state)
            result["tool_calls"].append(
                {"name": fc.name, "args": args, "ok": bool(out.get("ok"))}
            )
            response_parts.append(
                types.Part.from_function_response(name=fc.name, response=out)
            )
        contents.append(types.Content(role="user", parts=response_parts))

    result.update(status="max_steps", error=f"No final answer after {MAX_STEPS} steps.",
                  sql=state["sql"], rows=state["rows"], chart_path=state["chart_path"])
    return result


if __name__ == "__main__":
    import traceback

    q = input("Ask a question: ").strip()
    print(f"\nQuestion received: {q!r}")
    print("Calling Gemini (can take 10-60 seconds)...", flush=True)

    try:
        out = answer_with_tools(q)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)

    print("\nStatus:", out["status"])
    for c in out["tool_calls"]:
        print("Tool:", c["name"], "| ok:", c["ok"])
        print("   args:", c["args"])
        if c.get("error"):
            print("   error:", c["error"])
    if out["sql"]:
        print("SQL:", out["sql"])
    if out["chart_path"]:
        print("Chart saved:", out["chart_path"])
    if out["error"]:
        print("Error:", out["error"])
    print("API calls:", out["api_calls"], "| tokens in/out:",
          out["prompt_tokens"], "/", out["output_tokens"])
    print("\nAnswer:", out["answer"])