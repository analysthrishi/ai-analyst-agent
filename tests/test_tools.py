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

# --- error handling: these use a stubbed query runner, so no database is needed ---

@pytest.fixture
def stub_query(monkeypatch, tmp_path):
    import pandas as pd
    import tools

    monkeypatch.setattr(tools, "CHART_DIR", tmp_path / "charts")

    def install(df=None, error=None):
        def fake(sql):
            if error:
                raise error
            return df
        monkeypatch.setattr(tools, "_run_df", fake)
    return install


def test_chart_non_numeric_y_is_an_error_not_a_crash(stub_query):
    import pandas as pd
    stub_query(pd.DataFrame({"a": ["x", "y"], "b": ["p", "q"]}))
    out = make_chart("SELECT 1 AS a, 2 AS b", kind="bar", x="a", y="b", title="t")
    assert not out["ok"]
    assert "numeric" in out["error"]


def test_chart_duplicate_column_names_do_not_crash(stub_query):
    import pandas as pd
    stub_query(pd.DataFrame([[1, 2]], columns=["a", "a"]))
    out = make_chart("SELECT 1 AS a, 2 AS a", kind="bar", x="a", y="a", title="t")
    assert not out["ok"]


def test_chart_plot_failure_returns_error_and_closes_figure(stub_query, monkeypatch):
    import matplotlib.pyplot as plt
    import pandas as pd
    import tools

    stub_query(pd.DataFrame({"a": ["x"], "b": [1]}))
    monkeypatch.setattr(tools.plt.Figure, "savefig", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    plt.close("all")
    out = make_chart("SELECT 1 AS a, 2 AS b", kind="bar", x="a", y="b", title="t")
    assert not out["ok"]
    assert "disk full" in out["error"]
    assert plt.get_fignums() == []


def test_chart_query_failure_is_an_error(stub_query):
    stub_query(error=RuntimeError("boom"))
    out = make_chart("SELECT 1 AS a, 2 AS b", kind="bar", x="a", y="b", title="t")
    assert not out["ok"]
    assert "SQL failed" in out["error"]


def test_rfm_database_failure_is_an_error_not_a_crash(stub_query):
    stub_query(error=RuntimeError("db locked"))
    out = rfm_segments()
    assert out["ok"] is False
    assert "db locked" in out["error"]


def test_same_title_charts_do_not_overwrite_each_other(stub_query):
    import pandas as pd
    stub_query(pd.DataFrame({"a": ["x", "y"], "b": [1, 2]}))
    first = make_chart("SELECT 1 AS a, 2 AS b", kind="bar", x="a", y="b", title="Same title")
    second = make_chart("SELECT 1 AS a, 2 AS b", kind="bar", x="a", y="b", title="Same title")
    assert first["ok"] and second["ok"]
    assert first["path"] != second["path"]
    assert Path(first["path"]).exists() and Path(second["path"]).exists()


def test_chart_filename_matches_the_api_chart_route(stub_query):
    import pandas as pd
    import api
    stub_query(pd.DataFrame({"a": ["x"], "b": [1]}))
    out = make_chart("SELECT 1 AS a, 2 AS b", kind="bar", x="a", y="b", title="Revenue by Month!")
    assert api.CHART_NAME.fullmatch(Path(out["path"]).name)
