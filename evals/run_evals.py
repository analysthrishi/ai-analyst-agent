import json
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
sys.path.insert(0, "src")
from baseagent import answer_question  # noqa: E402
from questions import QUESTIONS    # noqa: E402

PAUSE_SECONDS = 12  # raise this if you hit rate limits
VERSION = sys.argv[1] if len(sys.argv) > 1 else "baseline"


def norm(v):
    if isinstance(v, float):
        return round(v, 2)
    return str(v)


def results_match(gold_rows, agent_rows, ordered):
    if gold_rows is None or agent_rows is None:
        return False
    g = [tuple(norm(x) for x in r) for r in gold_rows]
    a = [tuple(norm(x) for x in r) for r in agent_rows]
    if len(g) != len(a):
        return False
    if not ordered:
        g, a = sorted(g, key=str), sorted(a, key=str)
    return all(set(gr).issubset(set(ar)) for gr, ar in zip(g, a))


def main():
    con = duckdb.connect("data/retail.duckdb", read_only=True)
    records = []

    for q in QUESTIONS:
        print(f"Running {q['id']}: {q['question']}")
        out = answer_question(q["question"], summarize_answer=False)
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