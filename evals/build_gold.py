import duckdb
from questions import QUESTIONS

con = duckdb.connect("data/retail.duckdb", read_only=True)

for q in QUESTIONS:
    print(f"\n{q['id']} [{q['category']}] {q['question']}")
    if q["gold_sql"] is None:
        print(f"  (no SQL) expected behaviour: {q['expected_behavior']}")
        continue
    print(con.sql(q["gold_sql"]))