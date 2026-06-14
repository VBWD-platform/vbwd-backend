"""Unified pricing — the single answer to "what is the netto / tax / brutto?".

S85.0 introduces a computed ``Price`` value object, a structural ``Priceable``
protocol, and the ``PriceFactory`` that turns any sellable into a ``Price``.
The package is core-agnostic: it depends only on the core ``Tax`` model, the
core settings store, and ``CurrencyService`` — never on a plugin model.
"""
from vbwd.pricing.price import Price, PriceTax
from vbwd.pricing.price_factory import PriceFactory
from vbwd.pricing.priceable import Priceable

__all__ = ["Price", "PriceTax", "Priceable", "PriceFactory"]
