The file `invoice.txt` is a supplier invoice. Extract its billed line items into `output/line_items.csv`.

Rules:

- Columns, in this order, with a header row: `sku,description,quantity,unit_price,line_total`.
- `sku` is the code after `SKU` (for example `BW-1102`).
- `description` is the item text exactly as printed between the SKU and `qty`, with no leading or trailing spaces.
- `quantity` is the whole number after `qty`.
- `unit_price` is the price after `@`, written with exactly two decimal places.
- `line_total` is quantity times unit price, written with exactly two decimal places.
- Skip any item marked `REMOVED`; it is not billed.
- Do not include subtotal, tax or total lines.
- Keep the items in the order they appear on the invoice.

Descriptions contain commas, so write the file with a proper CSV writer that quotes those fields.
