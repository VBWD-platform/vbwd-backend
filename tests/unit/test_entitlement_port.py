"""S3 — core entitlement port + D3 default behaviour.

Core must not know subscription: `vbwd/services/feature_guard.py` is gone,
the permission decorators resolve a generic provider, and with no provider
registered the D3 default (config-flag, default allow) applies.
"""
import importlib.util

import pytest

from vbwd.services.entitlement import (
    IEntitlementProvider,
    register_entitlement_provider,
    clear_entitlement_provider,
    resolve_entitlement_provider,
)


@pytest.fixture(autouse=True)
def _reset_provider():
    clear_entitlement_provider()
    yield
    clear_entitlement_provider()


def test_core_feature_guard_module_is_gone():
    assert importlib.util.find_spec("vbwd.services.feature_guard") is None


def test_default_provider_allows_when_no_provider_registered(app):
    """D3: subscription plugin disabled ⇒ allow by default."""
    with app.app_context():
        app.config.pop("ENTITLEMENT_DEFAULT_ALLOW", None)
        provider = resolve_entitlement_provider()
        assert provider.is_feature_allowed("u", "anything") is True
        assert provider.check_usage_limit("u", "anything", 1) == (True, None)


def test_default_provider_denies_when_flag_false(app):
    """D3: the core config flag can flip the default to deny."""
    with app.app_context():
        app.config["ENTITLEMENT_DEFAULT_ALLOW"] = False
        provider = resolve_entitlement_provider()
        assert provider.is_feature_allowed("u", "anything") is False
        assert provider.check_usage_limit("u", "anything", 1) == (False, 0)


def test_registered_provider_takes_precedence():
    class _Allow(IEntitlementProvider):
        def is_feature_allowed(self, user_id, feature_name):
            return feature_name == "ok"

        def check_usage_limit(self, user_id, feature_name, amount=1):
            return (True, 7)

        def get_feature_value(self, user_id, feature_name, default=None):
            return 42 if feature_name == "lim" else default

        def current_plan_name(self, user_id):
            return "Pro"

    register_entitlement_provider(_Allow())
    provider = resolve_entitlement_provider()
    assert provider.is_feature_allowed("u", "ok") is True
    assert provider.is_feature_allowed("u", "no") is False
    assert provider.check_usage_limit("u", "x") == (True, 7)
    assert provider.get_feature_value("u", "lim", 3) == 42
    assert provider.get_feature_value("u", "other", 3) == 3
    assert provider.current_plan_name("u") == "Pro"


def test_default_provider_feature_value_and_plan_name():
    """D3 default: no plan → caller's default + no plan name."""
    from vbwd.services.entitlement import _DefaultEntitlementProvider

    provider = _DefaultEntitlementProvider()
    assert provider.get_feature_value("u", "daily_taro_limit", 3) == 3
    assert provider.current_plan_name("u") is None


def test_permission_decorators_use_the_port_not_a_container_factory():
    import inspect
    from vbwd.decorators import permissions

    source = inspect.getsource(permissions)
    assert "feature_guard()" not in source
    assert "resolve_entitlement_provider" in source
