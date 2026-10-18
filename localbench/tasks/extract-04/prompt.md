The files `release_1.txt` and `release_2.txt` are two press releases from the same company. The second one updates the first. Extract every appointment into `output/appointments.csv`.

Rules:

- Columns, in this order, with a header row: `name,new_title,previous_title,effective_date`.
- One row per person appointed, across both releases.
- `name` is the person's full name as printed (first name then last name).
- `new_title` is the title they are appointed to, exactly as printed.
- `previous_title` is the title they held at the company right before the appointment, exactly as printed. Leave it empty for someone joining from outside the company.
- `effective_date` is the date the appointment takes effect, as `YYYY-MM-DD`.
- When the second release corrects a detail from the first, use the corrected detail.
- Sort rows by `effective_date`, earliest first; when two rows share a date, sort by `name` A to Z.

Some titles contain commas, so write the file with a proper CSV writer that quotes those fields.
