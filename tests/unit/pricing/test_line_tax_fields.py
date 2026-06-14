"""S85.4 — core helper that maps a computed ``Price`` to the recorded per-line
tax fields (net / tax / per-rate breakdown) at the cents rounding boundary.

This is the single source of truth (DRY) used by every plugin that builds an
invoice line item, so the breakdown→columns mapping lives in exactly one place.
"""
from decimal import Decimal

from vbwd.pricing.line_tax_fields import line_tax_fields
from vbwd.pricing.price import Price, PriceTax


def _vat_price() -> Price:
    return Price(
        netto=10.0,
        taxes=[PriceTax(code="VAT", name="VAT Germany", rate=19.0, amount=1.9)],
        brutto=11.9,
        currency="EUR",
    )


def test_maps_net_tax_and_breakdown_at_cents():
    fields = line_tax_fields(_vat_price())
    assert fields["net_amount"] == Decimal("10.00")
    assert fields["tax_amount"] == Decimal("1.90")
    assert fields["tax_breakdown"] == [
        {"code": "VAT", "name": "VAT Germany", "rate": 19.0, "amount": 1.90}
    ]


def test_quantity_scales_amounts():
    fields = line_tax_fields(_vat_price(), quantity=2)
    assert fields["net_amount"] == Decimal("20.00")
    assert fields["tax_amount"] == Decimal("3.80")
    assert fields["tax_breakdown"][0]["amount"] == 3.80


def test_taxless_price_yields_empty_breakdown_and_zero_tax():
    price = Price(netto=5.0, taxes=[], brutto=5.0, currency="EUR")
    fields = line_tax_fields(price)
    assert fields["net_amount"] == Decimal("5.00")
    assert fields["tax_amount"] == Decimal("0.00")
    assert fields["tax_breakdown"] == []


def test_multi_rate_breakdown_sums_to_tax_amount():
    price = Price(
        netto=100.0,
        taxes=[
            PriceTax(code="VAT", name="VAT Germany", rate=19.0, amount=19.0),
            PriceTax(code="ECO", name="Eco Tax", rate=2.5, amount=2.5),
        ],
        brutto=121.5,
        currency="EUR",
    )
    fields = line_tax_fields(price)
    assert fields["tax_amount"] == Decimal("21.50")
    summed = sum(Decimal(str(line["amount"])) for line in fields["tax_breakdown"])
    assert summed == fields["tax_amount"]
