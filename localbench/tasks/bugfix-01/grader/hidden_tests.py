from pager import get_page, page_count


def test_first_page_items():
    assert get_page(list(range(10)), 1, 3)["items"] == [0, 1, 2]


def test_middle_page_items():
    assert get_page(list(range(10)), 2, 3)["items"] == [3, 4, 5]


def test_last_partial_page():
    assert get_page(list(range(10)), 4, 3)["items"] == [9]


def test_page_past_end_is_empty():
    result = get_page(list(range(10)), 5, 3)
    assert result["items"] == [] and result["total_pages"] == 4


def test_works_on_strings():
    assert get_page("abcdefg", 2, 3)["items"] == ["d", "e", "f"]


def test_has_next_flags():
    assert get_page(list(range(10)), 3, 3)["has_next"] is True
    assert get_page(list(range(10)), 4, 3)["has_next"] is False


def test_page_count_rounds_up():
    assert page_count(10, 3) == 4
    assert page_count(1, 3) == 1


def test_invalid_arguments_rejected():
    for page, per_page in ((0, 3), (-1, 3), (1, 0)):
        try:
            get_page([1, 2, 3], page, per_page)
        except ValueError:
            continue
        raise AssertionError((page, per_page))
