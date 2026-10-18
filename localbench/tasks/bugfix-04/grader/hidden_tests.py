from datetime import date

from spans import DateRange, filter_events, ranges_on

MARCH = DateRange(date(2025, 3, 1), date(2025, 3, 5))


def test_contains_end_day():
    assert MARCH.contains(date(2025, 3, 5)) is True


def test_contains_start_day():
    assert MARCH.contains(date(2025, 3, 1)) is True


def test_single_day_range():
    day = date(2025, 6, 9)
    assert DateRange(day, day).contains(day) is True


def test_filter_events_keeps_last_day():
    events = [("kickoff", date(2025, 3, 1)), ("review", date(2025, 3, 5)), ("late", date(2025, 3, 6))]
    assert filter_events(events, MARCH) == [("kickoff", date(2025, 3, 1)), ("review", date(2025, 3, 5))]


def test_ranges_on_shared_boundary():
    first = DateRange(date(2025, 3, 1), date(2025, 3, 5))
    second = DateRange(date(2025, 3, 5), date(2025, 3, 8))
    assert ranges_on(date(2025, 3, 5), [first, second]) == [first, second]


def test_days_outside_rejected():
    assert MARCH.contains(date(2025, 2, 28)) is False
    assert MARCH.contains(date(2025, 3, 6)) is False


def test_touching_ranges_overlap():
    assert MARCH.overlaps(DateRange(date(2025, 3, 5), date(2025, 3, 8))) is True


def test_days_lists_every_day():
    assert MARCH.days() == [date(2025, 3, d) for d in range(1, 6)]
