| q04 | highest revenue by month| Both answers got same answer but agent couldnt format in proper month and year formats
| q-8 |share of revenue comes from the top 10% of customers? |  - Same number of rows but different values. Compare filters, definitions and how percentages are calculated.
day2
| q12, q13 | Unanswerable questions | Model replied correctly but wrapped CANNOT_ANSWER in a ```sql fence; parser ran it as SQL | Made decline detection fence-tolerant | parsing bug, not model error |

Version	Score	Change
baseline_v1	11/13	First run. Includes the percent-formatting rule.
v2_parse_fix	13/13 (expected)	Decline detection tolerates code fences.