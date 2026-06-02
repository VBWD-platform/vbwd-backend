"""Core checkout price-adjustment registry — generic seam, no discount domain.

The empty registry (discount plugin disabled) must degrade gracefully: a no-op
zero adjustment, ``valid=True``, so checkout behaves as it does today.
"""
from decimal import Decimal

import pytest

from vbwd.services.checkout_price_adjustment_registry import (
    PriceAdjustmentResult,
    clear_price_adjustments,
    register_price_adjustment,
    resolve_price_adjustment,
    unregister_price_adjustment,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_price_adjustments()
    yield
    clear_price_adjustments()


def _resolve(code):
    return resolve_price_adjustment(
        code=code,
        subtotal=Decimal("100.00"),
        user_id="u1",
        scope="SUBSCRIPTION",
        currency="EUR",
    )


def test_empty_registry_no_code_is_valid_zero():
    result = _resolve(None)
    assert isinstance(result, PriceAdjustmentResult)
    assert result.valid is True
    assert result.discount_amount == Decimal("0")


def test_empty_registry_with_code_ignores_it_valid_zero():
    # Disabled-plugin Liskov path: a code with nothing to honour it is ignored,
    # checkout proceeds at full price (valid, zero) rather than hard-failing.
    result = _resolve("SUMMER2026")
    assert result.valid is True
    assert result.discount_amount == Decimal("0")


def test_registered_adjustment_is_invoked_with_keyword_terms():
    captured = {}

    def fake_adjustment(*, code, subtotal, user_id, scope, currency):
        captured.update(
            code=code,
            subtotal=subtotal,
            user_id=user_id,
            scope=scope,
            currency=currency,
        )
        return PriceAdjustmentResult(
            valid=True, discount_amount=Decimal("30.00"), label="Coupon X"
        )

    register_price_adjustment("discount", fake_adjustment)
    result = _resolve("SUB30")

    assert result.discount_amount == Decimal("30.00")
    assert result.label == "Coupon X"
    assert captured == {
        "code": "SUB30",
        "subtotal": Decimal("100.00"),
        "user_id": "u1",
        "scope": "SUBSCRIPTION",
        "currency": "EUR",
    }


def test_invalid_code_surfaces_valid_false_and_error():
    def rejecting(*, code, subtotal, user_id, scope, currency):
        return PriceAdjustmentResult(valid=False, error="Coupon not found")

    register_price_adjustment("discount", rejecting)
    result = _resolve("NOPE")

    assert result.valid is False
    assert result.error == "Coupon not found"
    assert result.discount_amount == Decimal("0")


def test_unregister_restores_no_op():
    register_price_adjustment(
        "discount",
        lambda **_: PriceAdjustmentResult(discount_amount=Decimal("5.00")),
    )
    unregister_price_adjustment("discount")
    assert _resolve("WELCOME5").discount_amount == Decimal("0")
