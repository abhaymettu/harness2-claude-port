Users of the small `csvlite` package report that records come out with too many fields whenever a quoted value contains a comma.

The package lives in `csvlite/` and its existing tests are in `tests/`. Run them from your working directory with `python3 -m unittest discover -s tests -t .`.

Intended behaviour:

- `parse_line(line)` splits one line of comma-separated text into a list of strings.
- A field may be wrapped in double quotes. Inside a quoted field, a comma is part of the value, and two double quotes in a row (`""`) stand for one double quote character. The wrapping quotes are not part of the value.
- Empty fields, including a trailing one after a final comma, are empty strings.
- `parse(text)` treats the first non-blank line as the header and returns one dict per later non-blank line, mapping header names to field values. Header fields follow the same quoting rules.

What to do:

1. Find and fix the bug in the source under `csvlite/`, editing the files in place. Keep every public function name and signature as it is.
2. Write `output/CHANGES.md` with one short paragraph that explains what was wrong and how you fixed it.

Use the Python standard library only.
