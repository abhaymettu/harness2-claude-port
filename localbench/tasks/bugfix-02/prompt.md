Customers of the small `ledger` package report that some invoice totals come out one cent too low.

The package lives in `ledger/` and its existing tests are in `tests/`. Run them from your working directory with `python3 -m unittest discover -s tests -t .`.

Intended behaviour:

- Amounts are passed as decimal strings or `Decimal` values. Every function returns `Decimal` values with exactly two decimal places.
- Rounding to cents rounds halves away from zero, the same as `decimal.ROUND_HALF_UP`: `0.125` becomes `0.13`, `2.675` becomes `2.68`, `-1.005` becomes `-1.01`.
- `to_money(value)` rounds one amount. `line_total(unit_price, quantity)` rounds the product. `apply_tax(amount, rate)` returns the rounded tax on an amount.
- `invoice_total(lines, tax_rate)` sums the rounded line totals into `subtotal`, computes `tax` on the subtotal, and returns `subtotal`, `tax` and `total` (subtotal plus tax).

What to do:

1. Find and fix the bug in the source under `ledger/`, editing the files in place. Keep every public function name and signature as it is.
2. Write `output/CHANGES.md` with one short paragraph that explains what was wrong and how you fixed it.

Use the Python standard library only.
