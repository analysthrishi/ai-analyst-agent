import duckdb

con = duckdb.connect("data/retail.duckdb", read_only=True)

print("Tables and views:")
print(con.sql("""
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = 'main'
"""))

for name in ["transactions", "sales", "cancellations"]:
    print(f"\nColumns in {name}:")
    print(con.sql(f"DESCRIBE {name}"))

print("\nFirst 5 rows of transactions:")
print(con.sql("SELECT * FROM transactions LIMIT 5"))

print("\nHow the views are defined:")
print(con.sql("SELECT view_name, sql FROM duckdb_views() WHERE NOT internal"))