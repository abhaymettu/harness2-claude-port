"""Split a sequence into fixed-size pages. Pages are numbered from 1."""


def page_count(total, per_page):
    """Number of pages needed to show `total` items, `per_page` at a time."""
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    return (total + per_page - 1) // per_page


def get_page(items, page, per_page):
    """Return one page of `items` plus navigation details."""
    if page < 1:
        raise ValueError("page must be at least 1")
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    total_pages = page_count(len(items), per_page)
    start = page * per_page
    return {
        "items": list(items[start:start + per_page]),
        "page": page,
        "total_pages": total_pages,
        "has_next": page < total_pages,
    }
