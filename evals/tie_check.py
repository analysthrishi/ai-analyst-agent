import duckdb

con = duckdb.connect("data/retail.duckdb", read_only=True)

print("q49: top 3 customers by cancellation rate")
print(con.sql("""
    SELECT customer_id,
           COUNT(DISTINCT CASE WHEN is_cancelled THEN invoice END) * 1.0
             / COUNT(DISTINCT invoice) AS rate,
           COUNT(DISTINCT invoice) AS invoices
    FROM transactions WHERE customer_id IS NOT NULL
    GROUP BY customer_id HAVING COUNT(DISTINCT invoice) >= 20
    ORDER BY rate DESC LIMIT 3
"""))

print("q46: top 3 countries by average order value")
print(con.sql("""
    SELECT country, SUM(revenue) / COUNT(DISTINCT invoice) AS aov,
           COUNT(DISTINCT invoice) AS invoices
    FROM sales GROUP BY country HAVING COUNT(DISTINCT invoice) >= 50
    ORDER BY aov DESC LIMIT 3
"""))
