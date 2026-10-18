# Business definitions

- Revenue = quantity * price, on valid sales only.
- Valid sale = not cancelled, a real product, quantity > 0, price > 0.
- Cancellation = invoice number starting with "C". Reported separately, never counted in revenue.
- Non-product rows (postage, fees, adjustments, samples) = stock codes that do not start with 5 digits. Excluded from product questions.
- Customer-level questions only use rows with a customer_id.
- Exact duplicate rows are removed.
## Known limitations of the cleaning rules
- Product rule keeps only stock codes starting with 5 digits. A few genuine
  gift-shop items (codes starting with DCGS) and gift vouchers are excluded.
- Exact duplicate rows were removed. This may include a few legitimate repeat
  line items, though most come from the overlap between the two yearly sheets.
- About 23% of rows have no customer ID (likely guest checkouts), so
  customer-level metrics cover only the identified customers.
  