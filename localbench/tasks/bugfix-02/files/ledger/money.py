"""Money helpers. Inputs are decimal strings or Decimals; results are Decimals with two places."""
from decimal import Decimal

CENT = Decimal("0.01")


def to_money(value):
    """Round `value` to whole cents, with halves rounded away from zero."""
    return Decimal(str(round(float(value), 2))).quantize(CENT)


def line_total(unit_price, quantity):
    """Price of `quantity` units, rounded to cents."""
    return to_money(Decimal(str(unit_price)) * quantity)


def apply_tax(amount, rate):
    """Tax owed on `amount` at `rate` (for example "0.05"), rounded to cents."""
    return to_money(Decimal(str(amount)) * Decimal(str(rate)))


def invoice_total(lines, tax_rate):
    """`lines` is a list of (unit_price, quantity). Returns subtotal, tax and total."""
    subtotal = sum((line_total(price, qty) for price, qty in lines), Decimal("0.00"))
    tax = apply_tax(subtotal, tax_rate)
    return {"subtotal": subtotal, "tax": tax, "total": subtotal + tax}
