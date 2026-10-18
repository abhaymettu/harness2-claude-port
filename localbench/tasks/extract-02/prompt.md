The file `policy.txt` sets out the rules for a grants program. List its deadlines in `output/deadlines.csv`.

Rules:

- Columns, in this order, with a header row: `section,title,deadline`.
- Make one row for each numbered section (`Section N.`) that states a specific calendar date as its deadline.
- Skip sections whose deadline is relative (for example "within 10 business days of a request") rather than a calendar date. Ignore dates outside the numbered sections, such as the publication date or office closures.
- `section` is the section number only (for example `4`).
- `title` is the heading text after `Section N. `, exactly as printed.
- `deadline` is the date in `YYYY-MM-DD` form. Ignore any time of day.
- Sort rows by `deadline`, earliest first. When two rows share a deadline, put the smaller section number first.
