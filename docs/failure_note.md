| q04 | highest revenue by month| Both answers got same answer but agent couldnt format in proper month and year formats
| q-8 |share of revenue comes from the top 10% of customers? |  - Same number of rows but different values. Compare filters, definitions and how percentages are calculated.
day2
| q12, q13 | Unanswerable questions | Model replied correctly but wrapped CANNOT_ANSWER in a ```sql fence; parser ran it as SQL | Made decline detection fence-tolerant | parsing bug, not model error |

Version	Score	Change
baseline_v1	11/13	First run. Includes the percent-formatting rule.
v2_parse_fix	13/13 (expected)	Decline detection tolerates code fences.


4 failed out of 13 in 'v4_batch1'

======================================================================
q15 [aggregation] How many invoices were placed in 2011?
Status: ok

AGENT SQL:
 SELECT COUNT(DISTINCT invoice) AS invoice_count FROM transactions WHERE EXTRACT(YEAR FROM invoice_date) = 2011 LIMIT 1000

GOLD SQL:
 SELECT COUNT(DISTINCT invoice) AS invoices FROM sales WHERE EXTRACT(year FROM invoice_date) = 2011

GOLD RESULT:
 [(18223,)]

AGENT RESULT:
 [(23875,)]

HINTS:
  - Used 'transactions' (includes cancellations and non-products) instead of 'sales'.
  - Same number of rows but different values. Compare filters, definitions and how percentages are calculated.

======================================================================
q19 [customer] Which country has the most customers?
Status: ok

AGENT SQL:
 SELECT country FROM sales WHERE NOT customer_id IS NULL GROUP BY country ORDER BY COUNT(DISTINCT customer_id) DESC LIMIT1

GOLD SQL:
 SELECT country, COUNT(DISTINCT customer_id) AS customers
                    FROM sales WHERE customer_id IS NOT NULL
                    GROUP BY 1 ORDER BY customers DESC LIMIT 1

GOLD RESULT:
 [('United Kingdom', 5334)]

AGENT RESULT:
 [('United Kingdom',)]

HINTS:
  - Same number of rows but different values. Compare filters, definitions and how percentages are calculated.

======================================================================
q21 [ranking] Which product description generated the most revenue?
Status: ok

AGENT SQL:
 SELECT description FROM sales GROUP BY description ORDER BY SUM(revenue) DESC LIMIT 1

GOLD SQL:
 SELECT description, ROUND(SUM(revenue), 2) AS revenue
                    FROM sales GROUP BY description ORDER BY revenue DESC LIMIT 1

GOLD RESULT:
 [('REGENCY CAKESTAND 3 TIER', 330590.32)]

AGENT RESULT:
 [('REGENCY CAKESTAND 3 TIER',)]

HINTS:
  - Same number of rows but different values. Compare filters, definitions and how percentages are calculated.

======================================================================
q24 [customer] How many customers made purchases in both 2010 and 2011?
Status: ok

AGENT SQL:
 SELECT COUNT(DISTINCT customer_id) AS customer_count FROM sales WHERE NOT customer_id IS NULL AND EXTRACT(YEAR FROM invoice_date) IN (2010, 2011) GROUP BY customer_id HAVING COUNT(DISTINCT EXTRACT(YEAR FROM invoice_date)) = 2 LIMIT 1000

GOLD SQL:
 WITH y AS (
                        SELECT customer_id, EXTRACT(year FROM invoice_date) AS yr
                        FROM sales WHERE customer_id IS NOT NULL GROUP BY 1, 2)
                    SELECT COUNT(*) AS customers FROM (
                        SELECT customer_id FROM y WHERE yr IN (2010, 2011)
                        GROUP BY 1 HAVING COUNT(DISTINCT yr) = 2) AS t

GOLD RESULT:
 [(2656,)]

AGENT RESULT:
 [(1,), (1,), (1,), (1,), (1,), (1,), (1,), (1,), (1,), (1,)]

HINTS:
  - Different row count (gold 1, agent 10). Check LIMIT and grouping.

| id | Question | What went wrong | Cause type | Fix | Result |
| q19 | Country with most customers | Gold returned an extra column the question didn't ask for | eval wrong | Gold now returns only the country | pass |
| q21 | Top product description | Same as q19 | eval wrong | Gold now returns only the description | pass |
| q15 | Invoices in 2011 | Agent used `transactions` (includes cancellations/non-products) | agent wrong | Prompt rule: default to `sales` | pass in v5_rules, 26/26 in regression |
| q24 | Customers active in both years | Agent grouped by customer then counted in same query | agent wrong | Prompt rule: aggregate per entity in a CTE, then count | pass in v5_rules, 26/26 in regression |


| q43 | MoM growth 2011 | Filtered to 2011 before LAG, so January was NULL | agent wrong | Rule: compute LAG over all periods, filter afterwards | see v8 |
| q48 | Top-5 stock code share | Ranked raw rows instead of grouping by stock code | agent wrong | Rule: aggregate per entity before ranking | see v8 |
| q50 | Days between 1st and 2nd order | "Order" undefined; agent used days, gold used invoices | ambiguous | Glossary defines order = invoice | see v8 |



Question	What the output shows	Class	Why
q43	The agent filtered to 2011 before calling LAG, so January’s growth is None. The gold computes over all months and filters afterwards, so January compares against Dec 2010 (-13.57%).	Agent wrong	The data to compute January’s growth exists. A business reader would want that number, not a blank. The other 11 months match exactly.
q48	The agent ranked individual rows (SELECT revenue FROM sales ORDER BY revenue DESC LIMIT 5), not stock codes. It never grouped by stock_code. Result 1.57% vs the correct 5.56%.	Agent wrong	The question says “5 stock codes”, so revenue must be summed per code first. This is a clear logic error.
q50	The agent treated each distinct day as an order. The gold treats each invoice as an order, so two invoices on one day count as two orders. 106.19 vs 99.02 days.	Ambiguous (missing definition)	Both readings are defensible, and the agent even wrote a comment saying so. Your glossary never defines “order”. My gold SQL assumed order = invoice, as did q06 (average order value) and q09 (repeat customers), without writing it down.