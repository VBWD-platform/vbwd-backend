"""S85.4 gap #2/#3 — the shared display-mode helper (DRY).

``display_mode_fields(priceable)`` is the ONE place that resolves the global
``prices_display_mode`` setting plus the per-item ``effective_display_mode``
(= per-item ``price_display_mode`` override ?? global). Every sellable payload
that needs the netto/brutto display pair reuses it, so the resolution lives in
exactly one place (it was previously copied across the catalog services).
"""
from unittest.mock import patch

from vbwd.pricing.display_mode import display_mode_fields


class _Priceable:
    def __init__(self, price_display_mode=None):
        self.price_display_mode = price_display_mode


def _settings(global_mode):
    return {"prices_display_mode": global_mode, "prices_mode_in_db": "NETTO"}


def test_no_override_uses_global():
    with patch(
        "vbwd.pricing.display_mode.get_core_settings",
        return_value=_settings("brutto"),
    ):
        fields = display_mode_fields(_Priceable(price_display_mode=None))

    assert fields == {
        "prices_display_mode": "brutto",
        "effective_display_mode": "brutto",
    }


def test_item_override_wins_over_global():
    with patch(
        "vbwd.pricing.display_mode.get_core_settings",
        return_value=_settings("brutto"),
    ):
        fields = display_mode_fields(_Priceable(price_display_mode="netto"))

    assert fields == {
        "prices_display_mode": "brutto",
        "effective_display_mode": "netto",
    }


def test_object_without_override_attr_still_resolves():
    class _Bare:
        pass

    with patch(
        "vbwd.pricing.display_mode.get_core_settings",
        return_value=_settings("netto"),
    ):
        fields = display_mode_fields(_Bare())

    assert fields == {
        "prices_display_mode": "netto",
        "effective_display_mode": "netto",
    }
