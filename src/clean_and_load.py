import pandas as pd
import duckdb
from pathlib import Path

RAW_FILE = Path("data/raw/online_retail_II.xlsx")  # change to your filename
DB_PATH = Path("data/retail.duckdb")

RENAME = {
    "Invoice": "invoice", "InvoiceNo": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "price", "UnitPrice": "price",
    "Customer ID": "customer_id", "CustomerID": "customer_id",
    "Country": "country",
}


def load_raw(path: Path) -> pd.DataFrame:
    if path.suffix == ".xlsx":
        sheets = pd.read_excel(path, sheet_name=None)
        return pd.concat(sheets.values(), ignore_index=True)
    return pd.read_csv(path, encoding="ISO-8859-1")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    report = {"raw_rows": len(df)}

    df = df.rename(columns=RENAME)

    before = len(df)
    df = df.drop_duplicates()
    report["duplicates_removed"] = before - len(df)

    df["invoice"] = df["invoice"].astype(str).str.strip()
    df["stock_code"] = df["stock_code"].astype(str).str.strip().str.upper()
    df["description"] = df["description"].astype("string").str.strip()
    df["invoice_date"] = pd.to_datetime(df["invoice_date"])
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["customer_id"] = pd.to_numeric(df["customer_id"], errors="coerce").astype("Int64")
    df["country"] = df["country"].astype("string").str.strip()

    df["is_cancelled"] = df["invoice"].str.startswith("C")
    df["is_product"] = df["stock_code"].str.match(r"^\d{5}")
    df["revenue"] = df["quantity"] * df["price"]

    report["cancelled_rows"] = int(df["is_cancelled"].sum())
    report["non_product_rows"] = int((~df["is_product"]).sum())
    report["missing_customer_id"] = int(df["customer_id"].isna().sum())
    report["zero_or_negative_price"] = int((df["price"] <= 0).sum())
    report["clean_rows"] = len(df)

    print("Cleaning report")
    for k, v in report.items():
        print(f"  {k}: {v:,}")
    return df


def load_to_duckdb(df: pd.DataFrame) -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.register("df_clean", df)
    con.execute("CREATE OR REPLACE TABLE transactions AS SELECT * FROM df_clean")
    con.execute("""
        CREATE OR REPLACE VIEW sales AS
        SELECT * FROM transactions
        WHERE NOT is_cancelled
          AND is_product
          AND quantity > 0
          AND price > 0
    """)
    con.execute("""
        CREATE OR REPLACE VIEW cancellations AS
        SELECT * FROM transactions WHERE is_cancelled
    """)
    con.close()
    print(f"Saved to {DB_PATH}")


if __name__ == "__main__":
    raw = load_raw(RAW_FILE)
    cleaned = clean(raw)
    load_to_duckdb(cleaned)