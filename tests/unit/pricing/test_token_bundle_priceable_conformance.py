"""S85.1 — core TokenBundle conforms to the core ``Priceable`` protocol.

After the storage migration the bundle exposes ``raw_price`` (a float reading
the stored ``price``) and a ``taxes`` relationship (via the new CORE↔CORE
``token_bundle_tax`` join). ``to_dict()`` keeps the raw ``price`` and carries no
``currency`` / ``price_float`` keys (the bundle never had them).
"""
from uuid import uuid4

from vbwd.models.token_bundle import TokenBundle
from vbwd.pricing.priceable import Priceable


def _bundle() -> TokenBundle:
    bundle = TokenBundle(name="Pack", token_amount=100, price=4.99)
    bundle.id = uuid4()
    bundle.taxes = []
    return bundle


def test_bundle_raw_price_returns_stored_price_float():
    bundle = _bundle()
    assert bundle.raw_price == 4.99
    assert isinstance(bundle.raw_price, float)


def test_bundle_has_taxes_relationship_assignable():
    assert hasattr(TokenBundle, "taxes")
    assert list(_bundle().taxes) == []


def test_to_dict_has_no_currency_or_price_float_keys():
    bundle_dict = _bundle().to_dict()
    assert "currency" not in bundle_dict
    assert "price_float" not in bundle_dict
    assert "price" in bundle_dict


def test_bundle_satisfies_priceable_protocol():
    assert isinstance(_bundle(), Priceable)
