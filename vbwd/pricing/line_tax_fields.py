"""Map a computed ``Price`` to the recorded per-line tax fields (S85.4).

The invoice line item is an immutable financial record (``Numeric(10,2)``
columns). This helper is the single place (DRY) that turns the full-precision
``Price`` value object into the recorded ``net_amount`` / ``tax_amount`` /
``tax_breakdown`` at the cents rounding boundary — the one legitimate place to
round (D4). Every plugin that builds an invoice line item uses it, so the
breakdown→columns mapping lives in exactly one place.

Core-only: depends solely on the core ``Price`` VO — no plugin import.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict

from vbwd.pricing.price import Price

_CENTS = Decimal("0.01")


def _to_cents(amount: float, quantity: int) -> Decimal:
    """Quantize ``amount * quantity`` to two decimal places (banker-safe)."""
    return (Decimal(str(amount)) * quantity).quantize(_CENTS, rounding=ROUND_HALF_UP)


def line_tax_fields(price: Price, quantity: int = 1) -> Dict[str, Any]:
    """Return the recorded ``{net_amount, tax_amount, tax_breakdown}`` for a line.

    Args:
        price: The computed ``Price`` for one unit of the sellable.
        quantity: Line quantity; the net/tax amounts scale linearly with it.

    Returns:
        A dict with cents-quantized ``net_amount`` and ``tax_amount`` Decimals
        plus a ``tax_breakdown`` list of ``{"code", "name", "rate", "amount"}``
        (amount is a cents-quantized float).
    """
    # Each per-rate amount is cents-quantized once. The stored ``tax_breakdown``
    # is JSONB, so amounts go in as ``float`` (JSON-safe); the rolled-up
    # ``tax_amount`` stays a Decimal for the ``Numeric(10,2)`` column, summed
    # from the same quantized values so it always equals their total.
    quantized_amounts = [_to_cents(tax.amount, quantity) for tax in price.taxes]
    breakdown = [
        {
            "code": tax.code,
            "name": tax.name,
            "rate": tax.rate,
            "amount": float(amount),
        }
        for tax, amount in zip(price.taxes, quantized_amounts)
    ]
    tax_total = sum(quantized_amounts, Decimal("0.00"))
    return {
        "net_amount": _to_cents(price.netto, quantity),
        "tax_amount": tax_total,
        "tax_breakdown": breakdown,
    }
