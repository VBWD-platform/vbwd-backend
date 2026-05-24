"""Deletion-dependency registry — plugins contribute user-deletion deps.

Core's ``/admin/users/<id>/deletion-info`` reports a generic ``dependencies[]``
list; core names no plugin domain. With nothing registered the list is empty
(the disabled-plugin path).
"""
from uuid import uuid4

import pytest

from vbwd.services.deletion_dependency_registry import (
    register_deletion_dependency_provider,
    unregister_deletion_dependency_provider,
    clear_deletion_dependency_providers,
    resolve_deletion_dependencies,
)


@pytest.fixture(autouse=True)
def _reset():
    clear_deletion_dependency_providers()
    yield
    clear_deletion_dependency_providers()


def test_no_providers_yields_empty():
    assert resolve_deletion_dependencies(uuid4()) == []


def test_registered_provider_contributes_when_count_positive():
    register_deletion_dependency_provider(
        "subscription",
        lambda _user_id: {"type": "subscription", "count": 3, "label": "Subscriptions"},
    )
    assert resolve_deletion_dependencies(uuid4()) == [
        {"type": "subscription", "count": 3, "label": "Subscriptions"}
    ]


def test_zero_count_provider_is_skipped():
    register_deletion_dependency_provider(
        "subscription",
        lambda _user_id: {"type": "subscription", "count": 0, "label": "Subscriptions"},
    )
    assert resolve_deletion_dependencies(uuid4()) == []


def test_none_provider_is_skipped():
    register_deletion_dependency_provider("subscription", lambda _user_id: None)
    assert resolve_deletion_dependencies(uuid4()) == []


def test_unregister_removes_only_that_provider():
    register_deletion_dependency_provider(
        "subscription",
        lambda _user_id: {"type": "subscription", "count": 1, "label": "Subscriptions"},
    )
    register_deletion_dependency_provider(
        "booking",
        lambda _user_id: {"type": "booking", "count": 2, "label": "Bookings"},
    )
    unregister_deletion_dependency_provider("subscription")
    assert resolve_deletion_dependencies(uuid4()) == [
        {"type": "booking", "count": 2, "label": "Bookings"}
    ]
