The file `orders.csv` in your working directory has order records whose dates were typed in several different styles. Write a cleaned copy to `output/orders_clean.csv`.

Rules:

- Keep the same four columns in the same order: `order_id,customer,order_date,amount`, with that header row.
- Rewrite every `order_date` as `YYYY-MM-DD`. The input uses exactly these styles: `2024-03-05`, `2024/03/05`, `03/05/2024` (slashes with the year last are always month first, US style), `5 Mar 2024`, and `March 5, 2024`.
- Remove leading and trailing spaces from `customer`.
- Write `amount` as a plain number with exactly two decimal places and no currency symbol (`$9.5` becomes `9.50`, `1250` becomes `1250.00`).
- Sort rows by `order_id`, smallest first.
- Keep every row; do not add or drop any.

Write a normal comma-separated file with a header row and one line per order.
