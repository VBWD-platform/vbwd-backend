"""Registry of checkout price adjustments (plugin-contributed, generic).

A checkout (subscription / shop / …) reduces its subtotal by asking this core
registry for an adjustment, passing only generic terms — a code, the subtotal,
the buyer, a scope string, a currency. Core names **no** discount domain: the
discount plugin registers an adjustment that knows coupon math; with nothing
registered (discount plugin disabled) the registry returns a **no-op** (zero
adjustment, ``valid=True``) so checkout behaves exactly as it does today — the
Liskov null-default.

Mirrors ``vbwd/services/deletion_dependency_registry.py`` and
``vbwd/events/line_item_registry.py``.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, Optional

# Called only after the invoice the adjustment applies to is actually
# persisted/paid — e.g. to redeem the coupon + record the application exactly
# once. Receives the new invoice id and the buyer id.
OnCommitted = Callable[[str, str], None]


@dataclass
class PriceAdjustmentResult:
    """Outcome of applying a code to a subtotal.

    ``valid=False`` + ``error`` means the caller must reject the checkout
    (4xx, no mutation). ``valid=True`` with ``discount_amount == 0`` is the
    no-code / disabled-plugin path.
    """

    valid: bool = True
    discount_amount: Decimal = Decimal("0")
    label: Optional[str] = None
    error: Optional[str] = None
    on_committed: Optional[OnCommitted] = None


# An adjustment resolves a code against a subtotal. Keyword-only so plugins are
# insulated from argument-order changes (DIP — both sides depend on this port).
CheckoutPriceAdjustment = Callable[..., PriceAdjustmentResult]

_adjustments: Dict[str, CheckoutPriceAdjustment] = {}


def register_price_adjustment(key: str, adjustment: CheckoutPriceAdjustment) -> None:
    """Register (or replace) a plugin's checkout price adjustment."""
    _adjustments[key] = adjustment


def unregister_price_adjustment(key: str) -> None:
    """Remove a plugin's adjustment (plugin disable)."""
    _adjustments.pop(key, None)


def clear_price_adjustments() -> None:
    """Reset all adjustments (test teardown)."""
    _adjustments.clear()


def resolve_price_adjustment(
    *,
    code: Optional[str],
    subtotal: Decimal,
    user_id: Optional[str],
    scope: str,
    currency: str,
) -> PriceAdjustmentResult:
    """Resolve a (possibly empty) code into a price adjustment.

    No code, or no registered adjustment (discount plugin disabled), yields a
    valid zero no-op. v1 honours a single coupon, so the first registered
    adjustment is used.
    """
    if not code:
        return PriceAdjustmentResult(valid=True, discount_amount=Decimal("0"))

    for adjustment in _adjustments.values():
        return adjustment(
            code=code,
            subtotal=subtotal,
            user_id=user_id,
            scope=scope,
            currency=currency,
        )

    # A code was supplied but nothing can honour it (plugin disabled): ignore it
    # and let checkout proceed at full price rather than hard-failing.
    return PriceAdjustmentResult(valid=True, discount_amount=Decimal("0"))
