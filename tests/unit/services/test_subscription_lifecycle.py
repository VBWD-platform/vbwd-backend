"""S17 — subscription_lifecycle port contract tests."""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.services.subscription_lifecycle import (
    ISubscriptionLifecycle,
    clear_subscription_lifecycle,
    register_subscription_lifecycle,
    resolve_subscription_lifecycle,
)


@pytest.fixture(autouse=True)
def _isolate():
    clear_subscription_lifecycle()
    yield
    clear_subscription_lifecycle()


class _FakeLifecycle(ISubscriptionLifecycle):
    def link_provider_subscription(self, invoice_id, provider_subscription_id):
        return None

    def record_provider_renewal(
        self, provider, provider_subscription_id, amount, currency, provider_reference
    ):
        return uuid4()

    def cancel_by_provider_subscription_id(
        self, provider, provider_subscription_id, reason=None
    ):
        return None

    def mark_provider_payment_failed(
        self, provider, provider_subscription_id, error_message
    ):
        return None

    def mark_invoice_payment_failed(
        self, invoice_id, provider, error_message, error_code="payment_failed"
    ):
        return None


def test_null_default_returns_none_for_record_provider_renewal():
    """Disabled-plugin path: no-op everything, returning None for the
    one method that has a return value."""
    lifecycle = resolve_subscription_lifecycle()
    result = lifecycle.record_provider_renewal(
        "stripe", "sub_x", Decimal("9.99"), "EUR", "evt_1"
    )
    assert result is None


def test_null_default_link_provider_subscription_is_noop():
    """No raise, no return value — pure no-op."""
    lifecycle = resolve_subscription_lifecycle()
    assert lifecycle.link_provider_subscription(uuid4(), "sub_x") is None


def test_null_default_cancel_by_provider_subscription_id_is_noop():
    lifecycle = resolve_subscription_lifecycle()
    assert lifecycle.cancel_by_provider_subscription_id("stripe", "sub_x") is None


def test_register_then_resolve_returns_the_lifecycle():
    fake = _FakeLifecycle()
    register_subscription_lifecycle(fake)
    assert resolve_subscription_lifecycle() is fake


def test_clear_returns_to_null_default():
    register_subscription_lifecycle(_FakeLifecycle())
    clear_subscription_lifecycle()
    lifecycle = resolve_subscription_lifecycle()
    assert not isinstance(lifecycle, _FakeLifecycle)


def test_double_register_replaces_previous():
    register_subscription_lifecycle(_FakeLifecycle())
    second = MagicMock(spec=ISubscriptionLifecycle)
    register_subscription_lifecycle(second)
    assert resolve_subscription_lifecycle() is second
