"""S85.2 — the public token-bundle payload carries the computed ``Price`` block.

``_bundle_dict_with_price`` routes the price math through the core
``PriceFactory`` (D1) and embeds the serialized ``Price``
(``{netto, taxes, brutto, currency}``) under ``price_info`` while keeping the
bare ``price`` field for backward compatibility. Flipping the global
``prices_mode_in_db`` changes net/gross for the SAME stored double.
"""
from unittest.mock import MagicMock

from vbwd.pricing.price_factory import PriceFactory
from vbwd.routes.token_bundles import _bundle_dict_with_price


class _FakeTax:
    def __init__(self, code, rate):
        self.code = code
        self.rate = rate


class _FakeBundle:
    def __init__(self, price, taxes):
        self.raw_price = price
        self.taxes = taxes
        self.name = "Starter"

    def to_dict(self):
        return {"name": self.name, "price": self.raw_price}


def _factory(prices_mode_in_db):
    settings_reader = MagicMock(return_value={"prices_mode_in_db": prices_mode_in_db})
    currency_service = MagicMock()
    currency_service.get_default_currency.return_value = MagicMock(code="EUR")
    return PriceFactory(
        settings_reader=settings_reader, currency_service=currency_service
    )


def _call(app, bundle, prices_mode_in_db):
    with app.app_context():
        app.container.price_factory = MagicMock(
            return_value=_factory(prices_mode_in_db)
        )
        return _bundle_dict_with_price(bundle)


def test_payload_keeps_bare_price_and_adds_price_info(app):
    result = _call(app, _FakeBundle(100.0, [_FakeTax("VAT_DE", 19.0)]), "NETTO")
    assert result["price"] == 100.0  # backward-compatible bare field
    assert result["price_info"]["price"]["netto"] == 100.0
    assert result["price_info"]["price"]["brutto"] == 119.0
    assert result["price_info"]["price"]["currency"] == "EUR"


def test_mode_flip_changes_net_and_gross_for_same_double(app):
    bundle = _FakeBundle(100.0, [_FakeTax("VAT_DE", 19.0)])
    netto = _call(app, bundle, "NETTO")["price_info"]
    brutto = _call(app, bundle, "BRUTTO")["price_info"]
    assert netto["gross_amount"] != brutto["gross_amount"]
    assert netto["net_amount"] != brutto["net_amount"]


def test_taxless_bundle_net_equals_gross(app):
    result = _call(app, _FakeBundle(50.0, []), "NETTO")
    assert result["price_info"]["net_amount"] == result["price_info"]["gross_amount"]
    assert result["price_info"]["taxes"] == []
