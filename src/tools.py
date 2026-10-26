import re
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # draw to files, no window
import matplotlib.pyplot as plt
import numpy as np

from guardrails import validate_sql

DB_PATH = "data/retail.duckdb"
CHART_DIR = Path("outputs/charts")
MAX_CHART_ROWS = 40


def _run_df(sql: str):
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


def make_chart(sql: str, kind: str, x: str, y: str, title: str) -> dict:
    """Run a validated SELECT and save a bar or line chart as a PNG."""
    if kind not in ("bar", "line"):
        return {"ok": False, "error": "kind must be 'bar' or 'line'."}

    ok, reason, safe_sql = validate_sql(sql)
    if not ok:
        return {"ok": False, "error": f"Blocked by guardrails: {reason}"}

    try:
        df = _run_df(safe_sql)
    except Exception as e:
        return {"ok": False, "error": f"SQL failed: {e}"}

    if df.empty:
        return {"ok": False, "error": "Query returned no rows."}
    for col in (x, y):
        if col not in df.columns:
            return {"ok": False, "error": f"Column '{col}' not in result. Columns: {list(df.columns)}"}

    df = df.head(MAX_CHART_ROWS)
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = df[x].astype(str)
    if kind == "bar":
        ax.bar(labels, df[y])
    else:
        ax.plot(labels, df[y], marker="o")
    ax.set_title(title)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()

    CHART_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:50] or "chart"
    path = CHART_DIR / f"{slug}.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)

    return {"ok": True, "path": str(path), "rows_plotted": len(df), "sql": safe_sql}


RFM_SQL = """
WITH snap AS (SELECT MAX(invoice_date) + INTERVAL 1 DAY AS d FROM sales),
base AS (
    SELECT customer_id,
           DATE_DIFF('day', MAX(invoice_date), (SELECT d FROM snap)) AS recency_days,
           COUNT(DISTINCT invoice) AS frequency,
           SUM(revenue) AS monetary
    FROM sales
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT customer_id, recency_days, frequency, monetary,
NTILE(5) OVER (ORDER BY recency_days DESC, customer_id) AS r,
NTILE(5) OVER (ORDER BY frequency ASC, customer_id) AS f,
NTILE(5) OVER (ORDER BY monetary ASC, customer_id) AS m
FROM base
"""

RFM_DEFINITION = (
    "RFM scores run 1-5 (5 is best). Recency is measured against the day after the last "
    "invoice in the data, not today. Segments are checked in this order: "
    "Champions (R,F,M all >= 4); Loyal (F >= 4, R >= 3); New or promising (R >= 4, F <= 2); "
    "At risk (R <= 2, F >= 3); Lost (R <= 2, F <= 2); everything else is Needs attention."
)


def rfm_segments() -> dict:
    """Score every identified customer on recency, frequency and monetary value."""
    df = _run_df(RFM_SQL)

    conditions = [
        (df["r"] >= 4) & (df["f"] >= 4) & (df["m"] >= 4),
        (df["f"] >= 4) & (df["r"] >= 3),
        (df["r"] >= 4) & (df["f"] <= 2),
        (df["r"] <= 2) & (df["f"] >= 3),
        (df["r"] <= 2) & (df["f"] <= 2),
    ]
    names = ["Champions", "Loyal", "New or promising", "At risk", "Lost"]
    df["segment"] = np.select(conditions, names, default="Needs attention")

    summary = (
        df.groupby("segment")
        .agg(customers=("customer_id", "count"),
             avg_recency_days=("recency_days", "mean"),
             avg_orders=("frequency", "mean"),
             total_revenue=("monetary", "sum"))
        .reset_index()
    )
    summary["share_of_customers_pct"] = (100 * summary["customers"] / len(df)).round(2)
    summary["share_of_revenue_pct"] = (100 * summary["total_revenue"] / df["monetary"].sum()).round(2)
    summary = summary.round({"avg_recency_days": 1, "avg_orders": 1, "total_revenue": 2})
    summary = summary.sort_values("total_revenue", ascending=False)

    return {
        "ok": True,
        "total_customers": int(len(df)),
        "definition": RFM_DEFINITION,
        "segments": summary.to_dict("records"),
    }