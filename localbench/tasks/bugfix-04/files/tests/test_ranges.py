import unittest
from datetime import date

from spans import DateRange


class DateRangeTest(unittest.TestCase):
    def test_length_counts_both_ends(self):
        self.assertEqual(DateRange(date(2025, 3, 1), date(2025, 3, 5)).length(), 5)

    def test_contains_middle_day(self):
        self.assertTrue(DateRange(date(2025, 3, 1), date(2025, 3, 5)).contains(date(2025, 3, 3)))

    def test_disjoint_ranges_do_not_overlap(self):
        a = DateRange(date(2025, 3, 1), date(2025, 3, 5))
        b = DateRange(date(2025, 3, 7), date(2025, 3, 9))
        self.assertFalse(a.overlaps(b))


if __name__ == "__main__":
    unittest.main()
