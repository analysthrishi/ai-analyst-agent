import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

ALLOWED_TABLES = {"sales", "transactions", "cancellations"}
MAX_ROWS = 1000

# Only these kinds of statement may run
ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# If any of these appear anywhere in the query, reject it
_BLOCKED_NAMES = [
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "AlterTable",
    "Command", "Copy", "Merge", "Pragma", "Set", "Use", "Attach", "Detach",
    "TruncateTable", "Transaction", "Commit", "Rollback", "Into",
]
BLOCKED_NODES = tuple(
    t for t in (getattr(exp, n, None) for n in _BLOCKED_NAMES) if t is not None
)

# DuckDB functions that can touch files or the system
BLOCKED_FUNCTIONS = {"glob", "getenv", "load_extension", "install_extension", "sniff_csv"}
BLOCKED_FUNCTION_PREFIXES = ("read_", "write_")


def validate_sql(sql: str) -> tuple[bool, str, str | None]:
    """Return (ok, reason, safe_sql). safe_sql has a LIMIT added if missing."""
    if not sql or not sql.strip():
        return False, "Empty query.", None

    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError as e:
        return False, f"Could not parse SQL: {str(e)[:150]}", None

    if len(statements) != 1:
        return False, "Exactly one SQL statement is allowed.", None

    tree = statements[0]

    if not isinstance(tree, ALLOWED_ROOTS):
        return False, "Only SELECT queries are allowed.", None

    for node in tree.walk():
        if isinstance(node, BLOCKED_NODES):
            return False, f"Disallowed operation: {type(node).__name__}.", None

    for node in tree.find_all(exp.Func):
        name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
        if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_FUNCTION_PREFIXES):
            return False, f"Function '{name}' is not allowed.", None

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            return False, "Table functions are not allowed.", None
        if table.db or table.catalog:
            return False, "Qualified table names are not allowed.", None
        name = table.name.lower()
        if name not in ALLOWED_TABLES and name not in cte_names:
            return False, f"Table '{name}' is not allowed. Use: {sorted(ALLOWED_TABLES)}.", None

    if isinstance(tree, exp.Select) and not tree.args.get("limit"):
        tree = tree.limit(MAX_ROWS)

    return True, "ok", tree.sql(dialect="duckdb")