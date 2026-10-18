import unittest

from csvlite import parse, parse_line


class ParseLineTest(unittest.TestCase):
    def test_plain_fields(self):
        self.assertEqual(parse_line("a,b,c"), ["a", "b", "c"])

    def test_empty_fields(self):
        self.assertEqual(parse_line("a,,c"), ["a", "", "c"])

    def test_doubled_quote(self):
        self.assertEqual(parse_line('"5"" tall",x'), ['5" tall', "x"])


class ParseTest(unittest.TestCase):
    def test_header_rows(self):
        self.assertEqual(parse("id,name\n1,Ada\n"), [{"id": "1", "name": "Ada"}])


if __name__ == "__main__":
    unittest.main()
