import pytest
from guardrails import validate_sql
from questions import QUESTIONS


@pytest.mark.parametrize("sql", [
    "SELECT SUM(revenue) FROM sales",
    "SELECT * FROM transactions LIMIT 5",
    "WITH t AS (SELECT country, SUM(revenue) r FROM sales GROUP BY 1) SELECT * FROM t",
    "SELECT 1",
])
def test_valid_queries_pass(sql):
    ok, reason, safe = validate_sql(sql)
    assert ok, reason
    assert safe is not None


@pytest.mark.parametrize("sql", [
    "DROP TABLE transactions",
    "DELETE FROM transactions",
    "UPDATE sales SET price = 0",
    "INSERT INTO transactions VALUES (1)",
    "CREATE TABLE x AS SELECT 1",
    "SELECT 1; DROP TABLE transactions",
    "ATTACH 'other.db' AS other",
    "PRAGMA database_list",
    "SELECT * FROM read_csv('secrets.csv')",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM not_a_table",
    "WITH x AS (DELETE FROM transactions RETURNING *) SELECT * FROM x",
    "",
    "this is not sql",
])
def test_dangerous_queries_blocked(sql):
    ok, reason, safe = validate_sql(sql)
    assert not ok, f"Should have been blocked: {sql}"
    assert safe is None


def test_limit_added_when_missing():
    ok, _, safe = validate_sql("SELECT * FROM sales")
    assert ok
    assert "LIMIT 1000" in safe.upper()


def test_existing_limit_kept():
    ok, _, safe = validate_sql("SELECT * FROM sales LIMIT 5")
    assert ok
    assert "LIMIT 5" in safe.upper()


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q["gold_sql"]], ids=lambda q: q["id"])
def test_all_gold_queries_pass_validator(q):
    ok, reason, _ = validate_sql(q["gold_sql"])
    assert ok, f"{q['id']}: {reason}"