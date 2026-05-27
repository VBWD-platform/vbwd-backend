"""S17 — deletion_dependency_registry contract tests.

This registry is multi-provider (keyed by plugin name) rather than
single-provider like entitlement / lifecycle / read models.
"""
from uuid import uuid4

import pytest

from vbwd.services.deletion_dependency_registry import (
    clear_deletion_dependency_providers,
    register_deletion_dependency_provider,
    resolve_deletion_dependencies,
    unregister_deletion_dependency_provider,
)


@pytest.fixture(autouse=True)
def _isolate():
    clear_deletion_dependency_providers()
    yield
    clear_deletion_dependency_providers()


def test_resolve_returns_empty_when_no_provider_registered():
    """Disabled-plugin path: user deletion proceeds with no extra warnings."""
    assert resolve_deletion_dependencies(uuid4()) == []


def test_register_provider_then_resolve_returns_its_dependencies():
    def subscription_provider(user_id):
        return {"label": "Active subscription", "count": 2}

    register_deletion_dependency_provider("subscription", subscription_provider)
    result = resolve_deletion_dependencies(uuid4())
    assert len(result) == 1
    assert result[0]["label"] == "Active subscription"
    assert result[0]["count"] == 2


def test_unregister_removes_just_that_provider():
    register_deletion_dependency_provider(
        "subscription", lambda uid: {"label": "Sub", "count": 1}
    )
    register_deletion_dependency_provider(
        "shop", lambda uid: {"label": "Order", "count": 5}
    )

    unregister_deletion_dependency_provider("subscription")
    result = resolve_deletion_dependencies(uuid4())
    labels = {item["label"] for item in result}
    assert labels == {"Order"}


def test_unregister_unknown_key_is_idempotent():
    """Unregistering a key never registered must not raise."""
    unregister_deletion_dependency_provider("never-registered")


def test_clear_all_providers():
    register_deletion_dependency_provider(
        "subscription", lambda uid: {"label": "Sub", "count": 1}
    )
    clear_deletion_dependency_providers()
    assert resolve_deletion_dependencies(uuid4()) == []


def test_double_register_same_key_replaces():
    register_deletion_dependency_provider(
        "subscription", lambda uid: {"label": "First", "count": 1}
    )
    register_deletion_dependency_provider(
        "subscription", lambda uid: {"label": "Second", "count": 99}
    )
    result = resolve_deletion_dependencies(uuid4())
    assert len(result) == 1
    assert result[0]["label"] == "Second"


def test_zero_count_provider_is_excluded_from_result():
    """The registry filters out providers that report a 0 count today —
    if you don't have any subscriptions, no 'Subscription: 0' line."""
    register_deletion_dependency_provider(
        "subscription", lambda uid: {"label": "Sub", "count": 0}
    )
    assert resolve_deletion_dependencies(uuid4()) == []
