"""The structural ``Priceable`` protocol (S85.0, D2).

This is how ``PriceFactory`` stays plugin-agnostic: it dispatches by protocol,
never by concrete type, so core never imports a plugin model (the agnosticism
oracle stays green). Every sellable — a core token bundle, a subscription
plan, a shop product — conforms simply by exposing these attributes.

``price_display_mode`` is optional; the factory reads it defensively via
``getattr(obj, "price_display_mode", None)`` so objects lacking it still
conform.
"""
from typing import Protocol, Sequence, runtime_checkable

from vbwd.models.tax import Tax


@runtime_checkable
class Priceable(Protocol):
    """Anything the ``PriceFactory`` can turn into a ``Price``.

    The two structural members below are the only ones a sellable MUST expose
    to conform (and the only ones ``isinstance`` checks). A sellable MAY also
    carry an optional ``price_display_mode: str | None`` (S72.4); the factory
    reads it defensively via ``getattr(obj, "price_display_mode", None)`` so an
    object lacking it still conforms.
    """

    raw_price: float
    taxes: Sequence[Tax]
