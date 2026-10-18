Users of the small `spans` package report that events on the last day of a date range are missing from `filter_events`.

The package lives in `spans/` and its existing tests are in `tests/`. Run them from your working directory with `python3 -m unittest discover -s tests -t .`.

Intended behaviour:

- A `DateRange(start, end)` covers every day from `start` to `end`, both days included. A range whose start and end are the same day covers that one day. `end` before `start` raises `ValueError`.
- `contains(day)` is true exactly for the days the range covers. `length()` counts the covered days and `days()` lists them in order.
- `overlaps(other)` is true when the two ranges share at least one day.
- `filter_events(events, date_range)` keeps the `(name, day)` pairs whose day the range covers, in their original order.
- `ranges_on(day, ranges)` returns the ranges that cover `day`, in their original order.

What to do:

1. Find and fix the bug in the source under `spans/`, editing the files in place. Keep every public function name and signature as it is.
2. Write `output/CHANGES.md` with one short paragraph that explains what was wrong and how you fixed it.

Use the Python standard library only.
