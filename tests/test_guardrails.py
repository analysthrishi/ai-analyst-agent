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


INVISIBLE_CHARS = "​‌‍⁠﻿ "


def test_zero_width_space_q30_passes():
    sql = ("SELECT COUNT(DISTINCT customer_id) AS customers\nFROM sales\n"
           "​WHERE country = 'France' AND customer_id IS NOT NULL;")
    ok, reason, safe = validate_sql(sql)
    assert ok, reason
    assert not any(c in safe for c in INVISIBLE_CHARS)


def test_nbsp_between_words_passes():
    ok, reason, safe = validate_sql("SELECT country FROM sales")
    assert ok, reason
    assert " " not in safe


@pytest.mark.parametrize("sql", [
    "DR​OP TABLE sales",
    "DELETE​ FROM transactions",
    "SELECT 1;​ DROP TABLE sales",
])
def test_invisible_chars_do_not_unblock_dangerous_queries(sql):
    ok, reason, safe = validate_sql(sql)
    assert not ok, f"Should have been blocked: {sql!r}"
    assert safe is None
    # Blocked by the real rules after normalising, not by a parse error
    assert not reason.startswith("Could not parse"), reason


@pytest.mark.parametrize("sql", ["SELECT (1 FROM sales", "SELECT * FROM sales WHERE"])
def test_parse_error_has_no_ansi_codes(sql):
    ok, reason, _ = validate_sql(sql)
    assert not ok
    assert reason.startswith("Could not parse"), reason
    assert "\x1b" not in reason


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q["gold_sql"]], ids=lambda q: q["id"])
def test_all_gold_queries_pass_validator(q):
    ok, reason, _ = validate_sql(q["gold_sql"])
    assert ok, f"{q['id']}: {reason}"

@pytest.mark.parametrize("sql", [
    # A CTE defined in a subquery must not whitelist the same name in the outer query
    "SELECT * FROM \"/tmp/x.csv\" WHERE EXISTS (WITH \"/tmp/x.csv\" AS (SELECT 1) SELECT 1)",
    "SELECT * FROM secret_table WHERE EXISTS (WITH secret_table AS (SELECT 1) SELECT 1)",
    "SELECT * FROM secret_table, (WITH secret_table AS (SELECT 1) SELECT * FROM secret_table) t",
    # A CTE is not visible to an earlier CTE
    "WITH a AS (SELECT * FROM b), b AS (SELECT 1) SELECT * FROM a",
])
def test_cte_name_does_not_whitelist_tables_outside_its_scope(sql):
    ok, reason, safe = validate_sql(sql)
    assert not ok, f"Should have been blocked: {sql}"
    assert safe is None
    assert "not allowed" in reason, reason


@pytest.mark.parametrize("sql", [
    "WITH a AS (SELECT * FROM sales), b AS (SELECT * FROM a) SELECT * FROM b",
    "WITH A AS (SELECT * FROM sales) SELECT * FROM a",
    "WITH a AS (SELECT 1 AS n) SELECT * FROM a x JOIN sales s ON s.quantity = x.n",
    "SELECT * FROM (WITH z AS (SELECT 1 AS n) SELECT * FROM z) t",
    "SELECT * FROM sales WHERE quantity IN (WITH z AS (SELECT 1) SELECT * FROM z)",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT * FROM r",
])
def test_cte_names_in_scope_still_allowed(sql):
    ok, reason, safe = validate_sql(sql)
    assert ok, reason
