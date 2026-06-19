"""Subscribable outbound-webhook event-type registry (core, agnostic).

A tiny process-level registry of ``{value, label}`` event names an admin may
subscribe to. Core seeds the event names it itself publishes (payment money
path + the ``*`` wildcard + ``webhook.test``). Plugins MAY register additional
event types from their ``on_enable`` via :func:`register_webhook_event_type`
without core naming any plugin.

This registry is *advisory* — it only powers the admin event-type dropdown.
Delivery itself relays whatever event name is published on the bus, so an
unlisted event still reaches a ``["*"]`` subscriber.
"""
from __future__ import annotations

import threading
from typing import Dict, List

# The wildcard "all events" entry.
WILDCARD_EVENT = "*"

# The synthetic event the admin "Test" button emits.
TEST_EVENT = "webhook.test"

_lock = threading.Lock()
_registry: Dict[str, str] = {}


def register_webhook_event_type(name: str, label: str) -> None:
    """Register a subscribable event type (idempotent; last label wins)."""
    with _lock:
        _registry[name] = label


def list_webhook_event_types() -> List[Dict[str, str]]:
    """Return the registered event types as ``[{value, label}, ...]``.

    The wildcard sorts first; the remainder are alphabetised by value so the
    admin dropdown is stable.
    """
    with _lock:
        items = dict(_registry)
    ordered = sorted(
        items.items(),
        key=lambda pair: (pair[0] != WILDCARD_EVENT, pair[0]),
    )
    return [{"value": value, "label": label} for value, label in ordered]


def seed_core_webhook_event_types() -> None:
    """Seed the event names core publishes on the bus + wildcard + test.

    Mirrors the real bus event names emitted by the core money path. Idempotent
    — safe to call once at app startup.
    """
    register_webhook_event_type(WILDCARD_EVENT, "All events")
    register_webhook_event_type(TEST_EVENT, "Webhook test")
    register_webhook_event_type("payment.captured", "Payment captured")
    register_webhook_event_type("payment.authorized", "Payment authorized")
    register_webhook_event_type("payment.refunded", "Payment refunded")
    register_webhook_event_type("payment.recurring_charge", "Recurring charge")
    register_webhook_event_type(
        "payment.provider_cancelled", "Provider recurring cancelled"
    )
    register_webhook_event_type("payment.recurring_failed", "Recurring charge failed")
    register_webhook_event_type("payment.invoice_failed", "Invoice payment failed")
    register_webhook_event_type("payment.provider_linked", "Provider link established")
    register_webhook_event_type("refund.reversed", "Refund reversed")
