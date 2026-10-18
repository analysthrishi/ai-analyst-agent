import os
import re
import time
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()  # Load environment variables from .env file

DB_PATH = Path("data/retail.duckdb")
GLOSSARY_PATH = Path("docs/glossary.md")
MODEL=os.environ["GEMINI_MODEL"]  

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def get_schema() -> str:
    """Get the schema of the DuckDB database as a string."""
    con = duckdb.connect(database=DB_PATH, read_only=True)
    lines=[]
    for name in ["sales","transactions","cancellations"]:
        cols =con.execute(f"DESCRIBE {name}").fetchall()
        col_txt = ",".join([f"{c[0]} {c[1]}" for c in cols])
        lines.append(f"{name}({col_txt})")
    con.close()
    return "\n".join(lines)

SYSTEM_PROMPT = f"""You are a careful data analyst writing DuckDB SQL.time

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
"""
def generate_sql(question: str) -> tuple[str, dict]:
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
    return (resp.text or "").strip(), meta


def extract_sql(text: str) -> str | None:
    match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def run_sql(sql: str):
    con = duckdb.connect(DB_PATH, read_only=True)
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


def answer_question(question: str, summarize_answer: bool = True) -> dict:
    result = {"question": question, "status": None, "sql": None,
              "columns": None, "rows": None, "answer": None, "error": None}

    text, meta = generate_sql(question)
    result.update(meta)

    if text.upper().startswith("REFUSE"):
        result.update(status="refuse", answer=text)
        return result
    if text.upper().startswith("CANNOT_ANSWER"):
        result.update(status="cannot_answer", answer=text)
        return result

    sql = extract_sql(text)
    if not sql:
        result.update(status="no_sql", error="No SQL block in model reply", answer=text)
        return result
    result["sql"] = sql

    try:
        columns, rows = run_sql(sql)
    except Exception as e:
        result.update(status="sql_error", error=str(e))
        return result

    result.update(status="ok", columns=columns, rows=rows)
    if summarize_answer:
        result["answer"] = summarize(question, sql, columns, rows)
    return result


if __name__ == "__main__":
    q = input("Ask a question about the retail data: ")
    out = answer_question(q)
    print("\nSQL:\n", out["sql"])
    print("\nRows:", out["rows"][:10] if out["rows"] else out["error"] or out["answer"])
    print("\nAnswer:", out["answer"])