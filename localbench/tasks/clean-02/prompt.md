The file `customers.csv` contains customer records with duplicates. Write a de-duplicated copy to `output/customers_dedup.csv`.

Rules:

- Output columns, in this order, with a header row: `customer_id,email,name,updated_at`.
- Normalise every email by removing leading and trailing spaces and lowercasing it. Write the normalised email in the output.
- Two rows are duplicates when their normalised emails are equal.
- From each group of duplicates keep exactly one row: the one with the latest `updated_at` (timestamps are `YYYY-MM-DD HH:MM`). If two or more rows share the latest timestamp, keep the one with the smallest `customer_id`.
- Copy `customer_id`, `name` and `updated_at` unchanged from the kept row. Do not merge fields from different rows.
- Rows with a unique email are kept as they are (with the email normalised).
- Sort the output by `customer_id`, smallest first.
