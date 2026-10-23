import os
import re
import time
from pathlib import Path
import hashlib
import json

import duckdb
from guardrails import validate_sql
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()  # Load environment variables from .env file

DB_PATH = Path("data/retail.duckdb")
GLOSSARY_PATH = Path("docs/glossary.md")
MODEL=os.environ["GEMINI_MODEL"]  

client=genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def get_schema() -> str:
    """Get the schema of the DuckDB database as a string."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    lines=[]
    for name in ["sales","transactions","cancellations"]:
        cols =con.execute(f"DESCRIBE {name}").fetchall()
        col_txt = ",".join([f"{c[0]} {c[1]}" for c in cols])
        lines.append(f"{name}({col_txt})")
    con.close()
    return "\n".join(lines)

SYSTEM_PROMPT = f"""You are a careful data analyst writing DuckDB SQL.

Tables and views in the database:
{get_schema()}
Notes:
- 'sales' is the clean view of valid sales. Use it for revenue, products and customers unless the question is about cancellations.
- 'transactions' has every row including cancellations. 'cancellations' has only cancelled rows.

Business definitions:
{GLOSSARY_PATH.read_text(encoding="utf-8")}

Rules:
- Reply with ONE SQL query inside a ```sql fenced block and nothing else.
- Use only SELECT statements.
- If the request asks to modify or delete data, reply exactly: REFUSE: <reason>
- If the data cannot answer the question (for example profit, costs, emails), reply exactly: CANNOT_ANSWER: <reason>
- When a question asks for a percentage, return a number from 0 to 100 (for example 63.89), not a fraction (0.6389). Round to 2 decimal places.
- Round money to 2 decimal places.
- Use the 'sales' view for any question about orders, invoices, customers, products or revenue. Use 'transactions' or 'cancellations' only when the question explicitly mentions cancellations, returns or all raw rows.
- To count entities (customers, products) that meet a condition spanning several groups, first build one row per entity in a CTE using GROUP BY and HAVING, then COUNT the rows in an outer query. Never put COUNT(DISTINCT x) in the same query that already groups by x.
Example (a different case from any test question): products sold in both the United Kingdom and France:
WITH per_product AS (
    SELECT stock_code FROM sales
    WHERE country IN ('United Kingdom', 'France')
    GROUP BY stock_code HAVING COUNT(DISTINCT country) = 2
)
SELECT COUNT(*) AS products FROM per_product
- For period-over-period change (LAG or LEAD), compute the metric for ALL periods in one CTE and apply LAG there, then filter to the requested periods in a later step, so the first requested period still has a previous value.
  Example (invoice counts, a different metric): 
  WITH all_months AS (SELECT strftime(invoice_date, '%Y-%m') AS month, COUNT(DISTINCT invoice) AS n FROM sales GROUP BY 1),
  with_prev AS (SELECT month, n, LAG(n) OVER (ORDER BY month) AS prev_n FROM all_months)
  SELECT month, n, prev_n FROM with_prev WHERE month LIKE '2011-%' ORDER BY month
- For "top N" of any entity (products, stock codes, customers, countries), first aggregate to one row per entity with GROUP BY, then rank and take N. Never rank raw rows. For a share of the total, the denominator is the total across all entities.
"""

CACHE_PATH = Path("data/llm_cache.json")  # data/ is gitignored


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    
def generate_sql(question: str) -> tuple[str, dict]:
    key = hashlib.sha256((MODEL + SYSTEM_PROMPT + question).encode("utf-8")).hexdigest()
    cache = _load_cache()
    if key in cache:
        return cache[key]["text"], {**cache[key]["meta"], "cached": True}

    start = time.time()
    resp = client.models.generate_content(
        model=MODEL,
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
        ),
    )
    usage = getattr(resp, "usage_metadata", None)
    meta = {
        "latency_s": round(time.time() - start, 2),
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
    }
    text = (resp.text or "").strip()
    if text:
        cache[key] = {"text": text, "meta": meta}
        _save_cache(cache)
    return text,{**meta, "cached": False}

def extract_sql(text: str) -> str | None:
    match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def run_sql(sql: str):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cur = con.execute(sql)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(1000)
        return columns, rows
    finally:
        con.close()


def summarize(question: str, sql: str, columns, rows) -> str:
    preview = [dict(zip(columns, r)) for r in rows[:20]]
    prompt = (
        f"Question: {question}\nSQL used: {sql}\nResult rows (up to 20): {preview}\n\n"
        "Answer the question in 2-3 plain sentences for a business reader. "
        "Use only the numbers in the result."
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0),
    )
    return (resp.text or "").strip()

def detect_decline(text: str) -> str | None:
    """Return 'refuse' or 'cannot_answer' if the reply is a decline, even inside a code fence."""
    cleaned = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE).strip().upper()
    if cleaned.startswith("REFUSE"):
        return "refuse"
    if cleaned.startswith("CANNOT_ANSWER"):
        return "cannot_answer"
    return None

MAX_RETRIES = 2

def answer_question(question: str, summarize_answer: bool = True) -> dict:
    result = {
        "question": question, "status": None, "sql": None,
        "columns": None, "rows": None, "answer": None, "error": None,
        "attempts": 0, "cached": True,
        "latency_s": 0.0, "prompt_tokens": 0, "output_tokens": 0,
    }

    contents = question
    last_sql, last_error = None, None

    for attempt in range(MAX_RETRIES + 1):
        result["attempts"] = attempt + 1

        try:
            text, meta = generate_sql(contents)
        except Exception as e:
            result.update(status="api_error", error=str(e))
            return result

        result["latency_s"] += meta.get("latency_s") or 0
        result["prompt_tokens"] += meta.get("prompt_tokens") or 0
        result["output_tokens"] += meta.get("output_tokens") or 0
        result["cached"] = result["cached"] and meta.get("cached", False)

        decline = detect_decline(text)
        if decline:
            result.update(status=decline, answer=text)
            return result

        sql = extract_sql(text)
        if not sql:
            last_sql, last_error = None, "Reply contained no ```sql block."
            result.update(status="no_sql", error=last_error, answer=text)
        else:
            ok, reason, safe_sql = validate_sql(sql)
            if not ok:
                # A blocked query is never retried: it is a safety decision.
                result.update(status="blocked", sql=sql, error=reason)
                return result

            result["sql"] = safe_sql
            try:
                columns, rows = run_sql(safe_sql)
            except Exception as e:
                last_sql, last_error = safe_sql, str(e)
                result.update(status="sql_error", error=last_error)
            else:
                result.update(status="ok", columns=columns, rows=rows, error=None)
                if summarize_answer:
                    result["answer"] = summarize(question, safe_sql, columns, rows)
                return result

        # Only SQL errors and missing SQL are retried
        contents = (
            f"{question}\n\nYour previous attempt failed.\n"
            f"Previous SQL:\n{last_sql}\nError:\n{last_error}\n"
            "Return one corrected query in a ```sql block."
        )

    return result


if __name__ == "__main__":
    q = input("Ask a question about the retail data: ")
    out = answer_question(q)
    print("\nSQL:\n", out["sql"])
    print("\nRows:", out["rows"][:10] if out["rows"] else out["error"] or out["answer"])
    print("\nAnswer:", out["answer"])