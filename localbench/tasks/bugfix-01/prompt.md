Users of the small `pager` package report that the first page of results skips items and the last page sometimes comes back empty.

The package lives in `pager/` and its existing tests are in `tests/`. Run them from your working directory with `python3 -m unittest discover -s tests -t .`.

Intended behaviour:

- Pages are numbered from 1. `get_page(items, page, per_page)` returns a dict with `items` (a list of that page's items), `page`, `total_pages` and `has_next`.
- Page 1 holds the first `per_page` items, page 2 the next `per_page`, and so on; the last page may be shorter. `items` can be any sliceable sequence, including a string.
- A page past the last one returns an empty `items` list.
- `has_next` is true only when a later page exists. `page_count(total, per_page)` rounds up.
- A `page` or `per_page` below 1 raises `ValueError`.

What to do:

1. Find and fix the bug in the source under `pager/`, editing the files in place. Keep every public function name and signature as it is.
2. Write `output/CHANGES.md` with one short paragraph that explains what was wrong and how you fixed it.

Use the Python standard library only.
