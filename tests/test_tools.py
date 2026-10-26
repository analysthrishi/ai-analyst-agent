from pathlib import Path

import pytest

from tools import make_chart, rfm_segments

needs_db = pytest.mark.skipif(
    not Path("data/retail.duckdb").exists(), reason="database not built"
)


@needs_db
def test_rfm_covers_every_customer():
    out = rfm_segments()
    assert out["ok"]
    assert sum(s["customers"] for s in out["segments"]) == out["total_customers"]
    assert out["total_customers"] == 5852


@needs_db
def test_rfm_shares_add_up():
    out = rfm_segments()
    assert abs(sum(s["share_of_customers_pct"] for s in out["segments"]) - 100) < 0.1
    assert abs(sum(s["share_of_revenue_pct"] for s in out["segments"]) - 100) < 0.1


@needs_db
def test_chart_is_created():
    out = make_chart(
        "SELECT strftime(invoice_date, '%Y-%m') AS month, SUM(revenue) AS revenue "
        "FROM sales GROUP BY 1 ORDER BY 1",
        kind="line", x="month", y="revenue", title="Test monthly revenue",
    )
    assert out["ok"], out
    assert Path(out["path"]).exists()


def test_chart_blocks_dangerous_sql():
    out = make_chart("DROP TABLE sales", kind="bar", x="a", y="b", title="bad")
    assert not out["ok"]
    assert "Blocked" in out["error"]


def test_chart_rejects_bad_kind():
    out = make_chart("SELECT 1 AS a, 2 AS b", kind="pie", x="a", y="b", title="x")
    assert not out["ok"]


@needs_db
def test_chart_rejects_missing_column():
    out = make_chart("SELECT 1 AS a, 2 AS b", kind="bar", x="a", y="nope", title="x")
    assert not out["ok"]

@needs_db
def test_rfm_is_deterministic():
    assert rfm_segments()["segments"] == rfm_segments()["segments"]