import json
import sys

import duckdb
from questions import QUESTIONS

VERSION = sys.argv[1] if len(sys.argv) > 1 else "baseline"
with open(f"evals/results/{VERSION}.json", encoding="utf-8") as f:
    data = json.load(f)

gold_by_id = {q["id"]: q for q in QUESTIONS}
con = duckdb.connect("data/retail.duckdb", read_only=True)


def run(sql):
    if not sql:
        return None
    try:
        return con.execute(sql).fetchmany(10)
    except Exception as e:
        return f"ERROR: {e}"


def get_hints(rec, q, gold_rows, agent_rows):
    hints = []
    sql = (rec["agent_sql"] or "").lower()
    status = rec["status"]

    if q["gold_sql"] and status in ("refuse", "cannot_answer"):
        hints.append("Agent declined a question that CAN be answered from the data.")
    if q["gold_sql"] is None and status == "ok":
        hints.append("Agent answered something it should have refused or said it cannot answer.")
    if status == "no_sql":
        hints.append("Model reply had no ```sql block. Check the output format rules.")
    if status == "sql_error":
        hints.append("SQL failed to run. Look at the error: wrong column, wrong function, bad syntax?")
    if "from transactions" in sql and "sales" not in sql:
        hints.append("Used 'transactions' (includes cancellations and non-products) instead of 'sales'.")
    if isinstance(agent_rows, list) and len(agent_rows) == 0:
        hints.append("Query ran but returned no rows. Check filters and date formats.")
    if isinstance(gold_rows, list) and isinstance(agent_rows, list) and agent_rows:
        if len(gold_rows) != len(agent_rows):
            hints.append(f"Different row count (gold {len(gold_rows)}, agent {len(agent_rows)}). Check LIMIT and grouping.")
        else:
            hints.append("Same number of rows but different values. Compare filters, definitions and how percentages are calculated.")
    return hints


failed = [r for r in data["records"] if not r["passed"]]
print(f"{len(failed)} failed out of {data['total']} in '{VERSION}'\n")

for rec in failed:
    q = gold_by_id[rec["id"]]
    gold_rows = run(q["gold_sql"])
    agent_rows = run(rec["agent_sql"])

    print("=" * 70)
    print(f"{rec['id']} [{rec['category']}] {rec['question']}")
    print(f"Status: {rec['status']}")
    print("\nAGENT SQL:\n", rec["agent_sql"])
    print("\nGOLD SQL:\n", q["gold_sql"])
    print("\nGOLD RESULT:\n", gold_rows)
    print("\nAGENT RESULT:\n", agent_rows if agent_rows is not None else rec["error"])
    print("\nHINTS:")
    for h in get_hints(rec, q, gold_rows, agent_rows):
        print("  -", h)
    print()