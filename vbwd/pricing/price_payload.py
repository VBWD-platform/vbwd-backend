"""Serialise a computed ``Price`` into the API ``pricing`` block (S85.2, DRY).

This is the ONE place that turns a ``Price`` value object (from ``PriceFactory``)
into the JSON ``pricing`` block every sellable route emits. It keeps the existing
backward-compatible keys (``net_amount`` / ``tax_amount`` / ``gross_amount`` /
``tax_rate`` / ``taxes``) and adds the serialized ``price`` object
(``Price.to_dict()``) so consumers can move to the unified shape.

The numbers come straight from the ``Price`` VO — no tax arithmetic happens here
(D1). Money values are quantized to two decimals only for the *display* strings
(the live VO stays full-precision, D4); the invoice write site does its own
documented rounding.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict

from vbwd.pricing.price import Price

_CENTS = Decimal("0.01")


def _money(amount: float) -> str:
    """Quantize a price amount to a two-decimal display string."""
    quantized = Decimal(str(amount)).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return str(quantized)


def build_pricing_block(price: Price) -> Dict[str, Any]:
    """Build the API ``pricing`` block from a computed ``Price``.

    Args:
        price: The computed value object from ``PriceFactory``.

    Returns:
        The backward-compatible breakdown block (stringified money) plus the
        serialized ``price`` object.
    """
    total_tax = sum((tax.amount for tax in price.taxes), 0.0)
    total_rate = sum((Decimal(str(tax.rate)) for tax in price.taxes), Decimal("0"))
    return {
        "net_amount": _money(price.netto),
        "tax_amount": _money(total_tax),
        "gross_amount": _money(price.brutto),
        "tax_rate": str(total_rate.quantize(_CENTS, rounding=ROUND_HALF_UP)),
        "taxes": [
            {"code": tax.code, "rate": str(tax.rate), "amount": _money(tax.amount)}
            for tax in price.taxes
        ],
        "price": price.to_dict(),
    }
