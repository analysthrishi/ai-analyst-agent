import pandas as pd
from pathlib import Path

RAW_FILE = Path("data/raw/online_retail_II.xlsx")  # change to your filename

if RAW_FILE.suffix == ".xlsx":
    sheets = pd.read_excel(RAW_FILE, sheet_name=None)
    print("Sheets:", list(sheets.keys()))
    df = pd.concat(sheets.values(), ignore_index=True)
else:
    df = pd.read_csv(RAW_FILE, encoding="ISO-8859-1")

print("\nShape:", df.shape)
print("\nColumn types:\n", df.dtypes)
print("\nFirst rows:\n", df.head())
print("\nMissing values:\n", df.isna().sum())
print("\nExact duplicate rows:", df.duplicated().sum())