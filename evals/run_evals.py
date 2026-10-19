import json
import sys
import time
from datetime import date,datetime
from pathlib import Path
from decimal import Decimal

import duckdb
sys.path.insert(0, "src")
from baseagent import answer_question  # noqa: E402
from questions import QUESTIONS    # noqa: E402

PAUSE_SECONDS = 12  # raise this if you hit rate limits
VERSION = sys.argv[1] if len(sys.argv) > 1 else "baseline"

ONLY = sys.argv[2].split(",") if len(sys.argv) > 2 else None


def is_num(v):
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)

def to_text(v):  # sourcery skip: assign-if-exp, reintroduce-else
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)

def cells_match(g, a):
    if is_num(g) and is_num(a):
        return abs(float(g) - float(a)) <= max(0.01, 1e-6 * abs(float(g)))
    if isinstance(a, (datetime, date)):
        # a date like 2011-11-01 matches a gold month like '2011-11'
        return to_text(a).startswith(to_text(g))
    return to_text(g) == to_text(a)


def row_match(gold_row, agent_row):
    # every value in the gold row must appear somewhere in the agent row
    return all(any(cells_match(g, a) for a in agent_row) for g in gold_row)


def results_match(gold_rows, agent_rows, ordered):
    if gold_rows is None or agent_rows is None:
        return False
    if len(gold_rows) != len(agent_rows):
        return False
    g, a = list(gold_rows), list(agent_rows)
    if not ordered:
        g, a = sorted(g, key=str), sorted(a, key=str)
    return all(row_match(gr, ar) for gr, ar in zip(g, a))


def main():
    con = duckdb.connect("data/retail.duckdb", read_only=True)
    records = []

    for q in QUESTIONS:
        if ONLY and q["id"] not in ONLY:
            continue
        print(f"Running {q['id']}: {q['question']}")
        out = answer_question(q["question"], summarize_answer=False)

        if out["status"] == "api_error":
            print("\nAPI error (probably quota). Stopping without saving results.")
            print(str(out["error"])[:300])
            return

        if not out.get("cached"):
            time.sleep(PAUSE_SECONDS)

        if q["gold_sql"] is None:
            passed = out["status"] in ("refuse", "cannot_answer")
        else:
            gold_rows = con.execute(q["gold_sql"]).fetchall()
            ordered = "ORDER BY" in q["gold_sql"].upper()
            passed = out["status"] == "ok" and results_match(gold_rows, out["rows"], ordered)

        records.append({
            "id": q["id"], "category": q["category"], "question": q["question"],
            "status": out["status"], "passed": passed, "agent_sql": out["sql"],
            "error": out["error"], "latency_s": out.get("latency_s"),
            "prompt_tokens": out.get("prompt_tokens"),
            "output_tokens": out.get("output_tokens"),
        })
        print("   ->", "PASS" if passed else "FAIL", f"({out['status']})")

    total = len(records)
    score = sum(r["passed"] for r in records)
    print(f"\nScore: {score}/{total} ({100 * score / total:.0f}%)")

    by_cat = {}
    for r in records:
        by_cat.setdefault(r["category"], []).append(r["passed"])
    for cat, vals in by_cat.items():
        print(f"  {cat}: {sum(vals)}/{len(vals)}")

    Path("evals/results").mkdir(parents=True, exist_ok=True)
    out_path = Path(f"evals/results/{VERSION}.json")
    out_path.write_text(json.dumps(
        {"version": VERSION, "run_at": datetime.now().isoformat(),
         "score": score, "total": total, "records": records}, indent=2),
        encoding="utf-8")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()