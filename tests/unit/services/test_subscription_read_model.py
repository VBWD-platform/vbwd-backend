"""S17 — subscription_read_model port contract tests."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.services.subscription_read_model import (
    ISubscriptionReadModel,
    clear_subscription_read_model,
    register_subscription_read_model,
    resolve_subscription_read_model,
)


@pytest.fixture(autouse=True)
def _isolate():
    clear_subscription_read_model()
    yield
    clear_subscription_read_model()


class _FakeReadModel(ISubscriptionReadModel):
    def enrich_invoice(self, invoice):
        return {"plan_name": "Fake Plan"}

    def count_user_subscriptions(self, user_id):
        return 3

    def user_addon_subscriptions(self, user_id):
        return [{"addon_id": "addon-1"}]

    def active_subscription_count(self):
        return 42


def test_null_default_returns_empty_enrichment_for_invoice():
    """Locked decision: disabled-plugin path yields empty/no error."""
    read_model = resolve_subscription_read_model()
    assert read_model.enrich_invoice(MagicMock()) == {}


def test_null_default_count_user_subscriptions_is_zero():
    assert resolve_subscription_read_model().count_user_subscriptions(uuid4()) == 0


def test_null_default_user_addon_subscriptions_is_empty():
    assert resolve_subscription_read_model().user_addon_subscriptions(uuid4()) == []


def test_null_default_active_subscription_count_is_zero():
    assert resolve_subscription_read_model().active_subscription_count() == 0


def test_register_then_resolve():
    fake = _FakeReadModel()
    register_subscription_read_model(fake)
    assert resolve_subscription_read_model() is fake


def test_clear_returns_to_null_default():
    register_subscription_read_model(_FakeReadModel())
    clear_subscription_read_model()
    assert resolve_subscription_read_model().enrich_invoice(MagicMock()) == {}


def test_double_register_replaces_previous():
    register_subscription_read_model(_FakeReadModel())
    second = MagicMock(spec=ISubscriptionReadModel)
    register_subscription_read_model(second)
    assert resolve_subscription_read_model() is second
