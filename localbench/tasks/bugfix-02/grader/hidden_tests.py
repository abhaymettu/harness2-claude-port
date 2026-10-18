from decimal import Decimal

from ledger import apply_tax, invoice_total, line_total, to_money


def test_half_cent_rounds_up():
    assert to_money("0.125") == Decimal("0.13")


def test_half_cent_not_lost_to_binary():
    assert to_money("2.675") == Decimal("2.68")
    assert to_money("1.005") == Decimal("1.01")


def test_negative_half_rounds_away_from_zero():
    assert to_money("-1.005") == Decimal("-1.01")


def test_two_places_kept():
    assert str(to_money("7")) == "7.00"
    assert to_money("19.99") == Decimal("19.99")


def test_line_total_half_cent():
    assert line_total("0.0125", 10) == Decimal("0.13")


def test_tax_half_cent():
    assert apply_tax("2.50", "0.05") == Decimal("0.13")


def test_invoice_total_with_halves():
    result = invoice_total([("4.99", 3), ("0.0125", 10), ("2.345", 1)], "0.05")
    assert result["subtotal"] == Decimal("17.45")
    assert result["tax"] == Decimal("0.87")
    assert result["total"] == Decimal("18.32")
