"""S85.0 oracle — unit tests for the core ``PriceFactory``.

TDD RED: written before ``vbwd/pricing/`` exists. The factory is the single
entry point for price math (D1); it stays plugin-agnostic by dispatching off
the structural ``Priceable`` protocol (D2) and never rounds (D4).

The settings store reader and the ``CurrencyService`` are both mocked: a
``FakePriceable`` stands in for any sellable (plugin or core) by exposing
``raw_price``, ``taxes`` and an optional ``price_display_mode``.
"""
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from vbwd.pricing.price import Price, PriceTax
from vbwd.pricing.price_factory import PriceFactory
from vbwd.pricing.priceable import Priceable


class FakeTax:
    """Minimal stand-in for a core ``Tax`` row: ``code`` + ``name`` + ``rate``."""

    def __init__(self, code: str, rate: float, name: str = ""):
        self.code = code
        self.rate = rate
        self.name = name or code


class FakePriceable:
    """A tiny object that conforms to the ``Priceable`` protocol."""

    def __init__(
        self,
        raw_price: float,
        taxes: List[FakeTax],
        price_display_mode: Optional[str] = None,
    ):
        self.raw_price = raw_price
        self.taxes = taxes
        if price_display_mode is not None:
            self.price_display_mode = price_display_mode


def _make_factory(prices_mode_in_db: str, currency_code: str = "EUR") -> PriceFactory:
    settings_reader = MagicMock(return_value={"prices_mode_in_db": prices_mode_in_db})
    currency_service = MagicMock()
    currency_service.get_default_currency.return_value = MagicMock(code=currency_code)
    return PriceFactory(
        settings_reader=settings_reader,
        currency_service=currency_service,
    )


def test_fake_priceable_conforms_to_protocol():
    """The structural protocol must accept any object with the attributes."""
    assert isinstance(FakePriceable(10.0, []), Priceable)


def test_netto_no_tax():
    """NETTO, no tax → netto == brutto == raw, taxes == []."""
    factory = _make_factory("NETTO")
    price = factory.get_price_from_object(FakePriceable(100.0, []))

    assert price.netto == 100.0
    assert price.brutto == 100.0
    assert price.taxes == []


def test_netto_one_tax_19_percent():
    """NETTO, one 19% tax → brutto == netto*1.19; one PriceTax(rate=19, amount=netto*0.19)."""
    factory = _make_factory("NETTO")
    price = factory.get_price_from_object(
        FakePriceable(100.0, [FakeTax("VAT_DE", 19.0, name="VAT Germany")])
    )

    assert price.netto == 100.0
    assert price.brutto == pytest.approx(100.0 * 1.19)
    assert len(price.taxes) == 1
    only_tax = price.taxes[0]
    assert only_tax.code == "VAT_DE"
    assert only_tax.name == "VAT Germany"
    assert only_tax.rate == 19.0
    assert only_tax.amount == pytest.approx(100.0 * 0.19)


def test_netto_two_taxes_additive():
    """NETTO, 19% + 7% → additive; Σamount == netto*0.26; invariant holds."""
    factory = _make_factory("NETTO")
    price = factory.get_price_from_object(
        FakePriceable(100.0, [FakeTax("VAT_DE", 19.0), FakeTax("VAT_RED", 7.0)])
    )

    total_tax = sum(tax.amount for tax in price.taxes)
    assert price.netto == 100.0
    assert total_tax == pytest.approx(100.0 * 0.26)
    assert price.netto + total_tax == pytest.approx(price.brutto)


def test_brutto_one_tax_19_percent():
    """BRUTTO, one 19% tax → netto == brutto/1.19; Σ tax == brutto − netto."""
    factory = _make_factory("BRUTTO")
    price = factory.get_price_from_object(
        FakePriceable(119.0, [FakeTax("VAT_DE", 19.0)])
    )

    assert price.brutto == 119.0
    assert price.netto == pytest.approx(119.0 / 1.19)
    total_tax = sum(tax.amount for tax in price.taxes)
    assert total_tax == pytest.approx(price.brutto - price.netto)
    assert price.netto + total_tax == pytest.approx(price.brutto)


def test_brutto_two_taxes_combined_divisor():
    """BRUTTO, 19% + 7% → combined divisor 1 + 0.26; invariant holds."""
    factory = _make_factory("BRUTTO")
    price = factory.get_price_from_object(
        FakePriceable(126.0, [FakeTax("VAT_DE", 19.0), FakeTax("VAT_RED", 7.0)])
    )

    assert price.brutto == 126.0
    assert price.netto == pytest.approx(126.0 / (1 + 0.26))
    total_tax = sum(tax.amount for tax in price.taxes)
    assert price.netto + total_tax == pytest.approx(price.brutto)


def test_factory_populates_tax_name_from_the_tax():
    """Each ``PriceTax`` carries the human-readable tax ``name`` (not just code)."""
    factory = _make_factory("NETTO")
    price = factory.get_price_from_object(
        FakePriceable(100.0, [FakeTax("VAT_DE", 19.0, name="VAT Germany")])
    )
    assert price.taxes[0].name == "VAT Germany"


def test_currency_is_the_default_currency_code():
    """``Price.currency`` is the default-currency code resolved by the service."""
    factory = _make_factory("NETTO", currency_code="USD")
    price = factory.get_price_from_object(FakePriceable(50.0, []))
    assert price.currency == "USD"


def test_factory_does_not_round():
    """No rounding: 9.99 + 19% must NOT be quantized to 2 decimal places."""
    factory = _make_factory("NETTO")
    price = factory.get_price_from_object(
        FakePriceable(9.99, [FakeTax("VAT_DE", 19.0)])
    )

    # Full-precision value preserved (within float tolerance) — not pre-rounded.
    assert price.brutto == pytest.approx(9.99 * 1.19)
    # And it genuinely is NOT the 2-dp value the display layer would produce.
    assert price.brutto != round(9.99 * 1.19, 2)


def test_price_to_dict_shape():
    """``Price.to_dict()`` exposes netto/taxes/brutto/currency with PriceTax dicts."""
    price = Price(
        netto=100.0,
        taxes=[PriceTax(code="VAT_DE", name="VAT Germany", rate=19.0, amount=19.0)],
        brutto=119.0,
        currency="EUR",
    )
    assert price.to_dict() == {
        "netto": 100.0,
        "taxes": [
            {"code": "VAT_DE", "name": "VAT Germany", "rate": 19.0, "amount": 19.0}
        ],
        "brutto": 119.0,
        "currency": "EUR",
    }


def test_price_display_mode_read_defensively_when_absent():
    """An object lacking ``price_display_mode`` still conforms and prices fine."""
    factory = _make_factory("NETTO")
    sellable = FakePriceable(10.0, [])
    assert not hasattr(sellable, "price_display_mode")
    price = factory.get_price_from_object(sellable)
    assert price.netto == 10.0
