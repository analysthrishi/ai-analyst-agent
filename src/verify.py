import duckdb

con = duckdb.connect("data/retail.duckdb", read_only=True)

print("Total rows:")
print(con.sql("SELECT COUNT(*) AS rows FROM transactions"))

print("Valid sales rows:")
print(con.sql("SELECT COUNT(*) AS rows FROM sales"))

print("Total revenue:")
print(con.sql("SELECT ROUND(SUM(revenue), 2) AS total_revenue FROM sales"))

print("Unique customers:")
print(con.sql("SELECT COUNT(DISTINCT customer_id) AS customers FROM sales"))

print("Top 5 countries by revenue:")
print(con.sql("""
    SELECT country, ROUND(SUM(revenue), 2) AS revenue
    FROM sales GROUP BY country ORDER BY revenue DESC LIMIT 5
"""))

print("Most common excluded (non-product) stock codes:")
print(con.sql("""
    SELECT stock_code, description, COUNT(*) AS n
    FROM transactions WHERE NOT is_product
    GROUP BY 1, 2 ORDER BY n DESC LIMIT 15
"""))