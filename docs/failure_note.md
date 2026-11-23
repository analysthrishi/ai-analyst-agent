# Failure notes

Every eval failure, what caused it, and how it was resolved. Run scores are in
the README results table; saved runs are in `evals/results/`.

**Cause types:** `agent wrong` (model logic error), `eval wrong` (gold SQL
problem), `parsing bug` (harness problem), `ambiguous` (question or glossary
did not define the term), `validator` (guardrail false positive).

## Summary

| id | Question | Cause type | Fix | Result |
|---|---|---|---|---|
| q04 | Highest revenue by month | agent wrong (formatting) | Not recorded | Fails in `baseline`, passes from `baseline_v1` |
| q08 | Share of revenue from the top 10% of customers | not recorded | Not recorded | Fails in `baseline` and `baseline_v1`, passes in `v2_parse_fix` |
| q12, q13 | Unanswerable questions | parsing bug | Decline detection tolerates code fences | Pass in `v2_parse_fix` |
| q15 | Invoices in 2011 | agent wrong | Prompt rule: default to `sales` | Pass in `v5_rules` |
| q19 | Country with most customers | eval wrong | Gold now returns only the country | Pass |
| q21 | Top product description | eval wrong | Gold now returns only the description | Pass |
| q24 | Customers active in both 2010 and 2011 | agent wrong | Prompt rule: aggregate per entity in a CTE, then count | Pass in `v5_rules` |
| q30 | (blocked by validator) | validator | Normalise invisible characters before parsing; add test | See below |
| q43 | MoM growth 2011 | agent wrong | Rule: compute LAG over all periods, filter afterwards | Pass in `v8_fixes` |
| q48 | Top-5 stock code share | agent wrong | Rule: aggregate per entity before ranking | Pass in `v8_fixes` |
| q50 | Days between 1st and 2nd order | ambiguous | Glossary defines order = invoice | Pass in `v8_fixes` |
| q53 | Days between 2nd and 3rd order | agent wrong (near miss) | Rule: identify orders by the invoice column | Pass in `v10_order` |

## Details

### q04 and q08 (baseline)
- **q04:** both answers had the same values, but the agent did not format the
  month and year the way the gold did.
- **q08:** same number of rows but different values. The comparison hint says to
  check filters, definitions and how percentages are calculated. The root cause
  was not written down at the time.

### q12, q13 (day 2)
The model replied correctly with `CANNOT_ANSWER` but wrapped it in a ```` ```sql ````
fence, so the parser ran it as SQL. This was a parsing bug, not a model error.
Fixing it took `baseline` 11/13 and `baseline_v1` 12/13 to 13/13 in `v2_parse_fix`.

### Batch 1 (`v4_batch1`, 9/13)
Failures were q15, q19, q21 and q24. Two were gold-SQL problems and two were
agent errors.

| id | What went wrong | Cause type |
|---|---|---|
| q15 | Agent used `transactions` (includes cancellations and non-products) and got 23875. Gold uses `sales` and gets 18223. | agent wrong |
| q19 | Gold returned an extra column (the customer count) that the question did not ask for. The agent's answer, United Kingdom, was right. | eval wrong |
| q21 | Same as q19: gold returned the revenue as well as the description. The agent's answer, REGENCY CAKESTAND 3 TIER, was right. | eval wrong |
| q24 | Agent grouped by customer and counted in the same query, so it returned many rows of 1 instead of one count (gold: 2656). | agent wrong |

q19 and q21 were re-run after fixing the gold (`v4_batch1_regold`, 2/2). q15 and
q24 were re-run under the new rules (`v5_rules`, 2/2), then the full regression
passed 26/26.

### Batch 3 (`v7_batch3`, 5/8)

**q43, agent wrong.** The agent filtered to 2011 before calling `LAG`, so
January's growth came out as `None`. The gold computes over all months and
filters afterwards, so January compares against December 2010 (-13.57%). The
other 11 months matched exactly. A business reader would want that number, not a
blank, and the data to compute it exists.

**q48, agent wrong.** The agent ranked individual rows
(`SELECT revenue FROM sales ORDER BY revenue DESC LIMIT 5`) instead of stock
codes. It never grouped by `stock_code`, so it returned 1.57% against the correct
5.56%. The question says "5 stock codes", so revenue must be summed per code
first.

**q50, ambiguous.** The agent treated each distinct day as an order and the gold
treated each invoice as an order, giving 106.19 against 99.02 days. Both readings
are defensible, and the agent wrote a comment saying so. The glossary did not
define "order". The gold SQL for q50, q06 (average order value) and q09 (repeat
customers) assumed order = invoice without writing it down. The glossary now
defines it.

These three were fixed with the window rule, the top-N rule and the glossary
definition, and passed in `v8_fixes` (3/3).

### q53 (`v9_fresh`, 3/4)
A fresh generalisation test. The window rule (1/1) and top-N rule (2/2) held. The
order definition did not: the agent used the invoice timestamp instead of the
invoice number as the order key, which gave 83.63 against 83.66 days. Fixed with a
rule to identify orders by the invoice column (`v10_order`, 3/3).

### q30 (validator false positive)
A regression run (`v8_regress_b`) showed q30 with status `blocked`. The model's
SQL contained an invisible zero-width space, so the validator rejected a harmless
question. I added a failing test, normalised invisible characters before parsing,
and verified that obfuscated attacks are still blocked. The post-fix full runs
(`v12_validator_fix` and `v13_after_fix`) both scored 55/55.

## Lessons
- When a question fails, check the gold SQL before blaming the agent (q19, q21).
- Undefined terms cause disagreements that look like agent errors (q50). Write
  the definition in the glossary.
- Rules written after one batch need a fresh held-out batch to show whether they
  generalise (q53 was a near miss).
