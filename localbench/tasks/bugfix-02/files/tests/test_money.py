import unittest
from decimal import Decimal

from ledger import invoice_total, to_money


class ToMoneyTest(unittest.TestCase):
    def test_already_cents(self):
        self.assertEqual(to_money("19.99"), Decimal("19.99"))

    def test_whole_number_gets_two_places(self):
        self.assertEqual(str(to_money("3")), "3.00")


class InvoiceTotalTest(unittest.TestCase):
    def test_simple_invoice(self):
        result = invoice_total([("2.50", 2), ("1.00", 3)], "0.10")
        self.assertEqual(result["subtotal"], Decimal("8.00"))
        self.assertEqual(result["tax"], Decimal("0.80"))
        self.assertEqual(result["total"], Decimal("8.80"))


if __name__ == "__main__":
    unittest.main()
