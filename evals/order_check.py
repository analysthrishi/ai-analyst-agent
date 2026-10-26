import duckdb

con = duckdb.connect("data/retail.duckdb", read_only=True)

print("Invoices whose rows have more than one distinct timestamp:")
print(con.sql("""
    SELECT COUNT(*) AS invoices FROM (
        SELECT invoice FROM sales
        GROUP BY invoice HAVING COUNT(DISTINCT invoice_date) > 1)
"""))

print("Customer + timestamp pairs shared by more than one invoice:")
print(con.sql("""
    SELECT COUNT(*) AS pairs FROM (
        SELECT customer_id, invoice_date FROM sales
        WHERE customer_id IS NOT NULL
        GROUP BY 1, 2 HAVING COUNT(DISTINCT invoice) > 1)
"""))