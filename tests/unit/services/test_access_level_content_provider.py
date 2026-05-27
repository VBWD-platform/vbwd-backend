"""S01 Part B — IAccessLevelContentProvider port contract.

Core's admin /api/v1/admin/access/user-levels/<id>/content route must reach
plugin-owned restricted-content data through this multi-provider registry,
never by importing plugin models. Tests cover:

  - null default — `resolve_*` returns an empty list when nothing is registered,
    so the route gracefully returns ``{}`` instead of 500'ing.
  - register / resolve round-trip.
  - clear (test teardown hook).
  - multi-provider — two providers' results are both returned.

These tests fail today because the port doesn't exist yet.
"""
from typing import Any, Mapping

import pytest

from vbwd.services.access_level_content_provider import (
    IAccessLevelContentProvider,
    clear_access_level_content_providers,
    register_access_level_content_provider,
    resolve_access_level_content_providers,
)


class _FakeCmsProvider(IAccessLevelContentProvider):
    def list_restricted_content_for_level(
        self, level_id: str
    ) -> Mapping[str, list[Mapping[str, Any]]]:
        return {
            "pages": [{"id": "p1", "name": "Home", "slug": "home"}],
            "widgets": [{"id": "w1", "area_name": "hero"}],
        }


class _FakeShopProvider(IAccessLevelContentProvider):
    def list_restricted_content_for_level(
        self, level_id: str
    ) -> Mapping[str, list[Mapping[str, Any]]]:
        return {"products": [{"id": "prod-1", "name": "Premium subscription"}]}


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with an empty registry; clean up on exit."""
    clear_access_level_content_providers()
    yield
    clear_access_level_content_providers()


def test_resolve_returns_empty_when_no_provider_registered():
    """Null default — disabled-plugin path is Liskov-safe (returns [], not raise)."""
    assert resolve_access_level_content_providers() == []


def test_register_then_resolve_returns_the_provider():
    provider = _FakeCmsProvider()
    register_access_level_content_provider(provider)
    assert resolve_access_level_content_providers() == [provider]


def test_clear_returns_to_null_default():
    register_access_level_content_provider(_FakeCmsProvider())
    clear_access_level_content_providers()
    assert resolve_access_level_content_providers() == []


def test_multiple_providers_are_all_returned():
    cms_provider = _FakeCmsProvider()
    shop_provider = _FakeShopProvider()
    register_access_level_content_provider(cms_provider)
    register_access_level_content_provider(shop_provider)
    providers = resolve_access_level_content_providers()
    assert providers == [cms_provider, shop_provider]


def test_provider_returns_categorized_content():
    """Contract: providers return ``Mapping[category, list[item]]``; merging
    across providers happens at the route layer, not the registry."""
    provider = _FakeCmsProvider()
    result = provider.list_restricted_content_for_level("level-id-1")
    assert "pages" in result
    assert "widgets" in result
    assert result["pages"][0]["slug"] == "home"
