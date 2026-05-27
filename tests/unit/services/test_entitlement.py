"""S17 worked example — entitlement port contract tests.

Covers the universal port-service shape that the rest of the backlog
follows (catalog_read_model, subscription_lifecycle, etc.):

  - Null default — ``resolve_*`` returns a Liskov-safe default when
    no provider is registered (D3: allow by default).
  - Override via ``ENTITLEMENT_DEFAULT_ALLOW=False`` config flag.
  - Register / resolve round-trip with a fake.
  - Clear / reset back to the null default.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.services.entitlement import (
    IEntitlementProvider,
    clear_entitlement_provider,
    register_entitlement_provider,
    resolve_entitlement_provider,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Each test starts and ends with no provider registered."""
    clear_entitlement_provider()
    yield
    clear_entitlement_provider()


class _FakeProvider(IEntitlementProvider):
    def is_feature_allowed(self, user_id, feature_name):
        return feature_name == "premium-feature"

    def check_usage_limit(self, user_id, feature_name, amount=1):
        return True, 99

    def get_feature_value(self, user_id, feature_name, default=None):
        return "value-from-fake"

    def current_plan_name(self, user_id):
        return "Pro"


# ── Null-default Liskov safety ─────────────────────────────────────────────


def test_null_default_allows_when_no_provider_registered(app):
    """D3 — disabled-plugin path is allow-by-default for booking/shop."""
    with app.app_context():
        provider = resolve_entitlement_provider()
        assert provider.is_feature_allowed(uuid4(), "anything") is True


def test_null_default_returns_none_for_current_plan_name(app):
    with app.app_context():
        provider = resolve_entitlement_provider()
        assert provider.current_plan_name(uuid4()) is None


def test_null_default_returns_callers_default_for_feature_value(app):
    with app.app_context():
        provider = resolve_entitlement_provider()
        assert provider.get_feature_value(uuid4(), "free-tier-limit", default=10) == 10


def test_null_default_check_usage_limit_returns_unlimited(app):
    with app.app_context():
        provider = resolve_entitlement_provider()
        within, remaining = provider.check_usage_limit(uuid4(), "x")
        assert within is True
        assert remaining is None


def test_default_deny_flag_flips_null_default(app):
    """Operators can flip the default to deny via core config."""
    app.config["ENTITLEMENT_DEFAULT_ALLOW"] = False
    try:
        with app.app_context():
            provider = resolve_entitlement_provider()
            assert provider.is_feature_allowed(uuid4(), "anything") is False
    finally:
        app.config["ENTITLEMENT_DEFAULT_ALLOW"] = True


# ── Register / resolve round-trip ──────────────────────────────────────────


def test_register_then_resolve_returns_the_provider():
    fake = _FakeProvider()
    register_entitlement_provider(fake)
    assert resolve_entitlement_provider() is fake


def test_clear_returns_to_null_default(app):
    register_entitlement_provider(_FakeProvider())
    clear_entitlement_provider()
    with app.app_context():
        # Re-resolve hits the default again.
        provider = resolve_entitlement_provider()
        assert not isinstance(provider, _FakeProvider)
        assert provider.is_feature_allowed(uuid4(), "x") is True


def test_double_register_replaces_previous():
    register_entitlement_provider(_FakeProvider())
    second = MagicMock(spec=IEntitlementProvider)
    register_entitlement_provider(second)
    assert resolve_entitlement_provider() is second
