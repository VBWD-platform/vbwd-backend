"""S85.2 — the shared ``Price`` → payload helper (DRY, D1).

``build_pricing_block(price)`` is the ONE place that turns a computed ``Price``
value object into the API ``pricing`` block every sellable route already emits
(``net_amount`` / ``tax_amount`` / ``gross_amount`` / ``tax_rate`` / ``taxes``)
PLUS the new serialized ``price`` object (``Price.to_dict()``). All money values
are stringified for JSON; the breakdown is derived from the VO, never recomputed.
"""
from vbwd.pricing.price import Price, PriceTax
from vbwd.pricing.price_payload import build_pricing_block


def _price(netto, taxes, brutto, currency="EUR"):
    return Price(netto=netto, taxes=taxes, brutto=brutto, currency=currency)


def test_block_carries_net_tax_gross_from_vo():
    price = _price(100.0, [PriceTax("VAT_DE", "VAT Germany", 19.0, 19.0)], 119.0)

    block = build_pricing_block(price)

    assert block["net_amount"] == "100.00"
    assert block["tax_amount"] == "19.00"
    assert block["gross_amount"] == "119.00"
    assert block["tax_rate"] == "19.00"


def test_block_lists_each_applied_tax():
    price = _price(
        100.0,
        [
            PriceTax("VAT_DE", "VAT Germany", 19.0, 19.0),
            PriceTax("ECO", "Eco Tax", 7.0, 7.0),
        ],
        126.0,
    )

    block = build_pricing_block(price)

    assert {tax["code"] for tax in block["taxes"]} == {"VAT_DE", "ECO"}
    assert block["tax_rate"] == "26.00"


def test_block_embeds_serialized_price_object():
    price = _price(100.0, [PriceTax("VAT_DE", "VAT Germany", 19.0, 19.0)], 119.0)

    block = build_pricing_block(price)

    assert block["price"] == price.to_dict()
    assert block["price"]["currency"] == "EUR"
    assert block["price"]["brutto"] == 119.0


def test_taxless_block_has_equal_net_and_gross():
    price = _price(50.0, [], 50.0)

    block = build_pricing_block(price)

    assert block["net_amount"] == "50.00"
    assert block["gross_amount"] == "50.00"
    assert block["tax_amount"] == "0.00"
    assert block["taxes"] == []
