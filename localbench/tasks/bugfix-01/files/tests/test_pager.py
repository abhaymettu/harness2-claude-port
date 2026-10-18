import unittest

from pager import get_page, page_count


class PageCountTest(unittest.TestCase):
    def test_exact_multiple(self):
        self.assertEqual(page_count(9, 3), 3)

    def test_empty(self):
        self.assertEqual(page_count(0, 5), 0)


class GetPageTest(unittest.TestCase):
    def test_rejects_page_zero(self):
        with self.assertRaises(ValueError):
            get_page([1, 2, 3], 0, 2)

    def test_has_next_on_first_page(self):
        self.assertTrue(get_page(list(range(9)), 1, 3)["has_next"])


if __name__ == "__main__":
    unittest.main()
