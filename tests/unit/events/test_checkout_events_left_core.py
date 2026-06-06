"""S50.6 — checkout events are subscription-domain and must leave core.

Core (`vbwd/`) names no `subscription`/`plan` vocabulary, so the checkout
event classes (fields `plan_id`, `subscription_id`, `addon_subscription_ids`)
must no longer live in or be exported from core. They moved to the subscription
plugin (`plugins/subscription/subscription/events.py`).
"""
import importlib

import pytest


def test_core_checkout_events_module_is_gone():
    """`vbwd.events.checkout_events` must no longer exist in core."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("vbwd.events.checkout_events")


def test_core_events_package_does_not_export_checkout_events():
    """The core events package must not re-export checkout event classes."""
    events_pkg = importlib.import_module("vbwd.events")
    for symbol in (
        "CheckoutRequestedEvent",
        "CheckoutCompletedEvent",
        "CheckoutFailedEvent",
    ):
        assert not hasattr(
            events_pkg, symbol
        ), f"vbwd.events must not export {symbol} — it is subscription-domain"
        assert symbol not in getattr(
            events_pkg, "__all__", []
        ), f"{symbol} must not be in vbwd.events.__all__"
