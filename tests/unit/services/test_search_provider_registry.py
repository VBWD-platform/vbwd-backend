"""Unit tests for the agnostic cross-entity search seam."""
import pytest

from vbwd.services.search import (
    GDPR_BLOCKED_ENTITY_TYPES,
    SearchHit,
    SearchProviderRegistry,
)


class _FakeProvider:
    def __init__(self, entity_type, entity_label, hits=None, raises=False):
        self.entity_type = entity_type
        self.entity_label = entity_label
        self._hits = hits or []
        self._raises = raises

    def search(self, query, *, limit=5):
        if self._raises:
            raise RuntimeError("boom")
        return [h for h in self._hits if query.lower() in h.title.lower()][:limit]

    def get_detail(self, key):
        return next((h for h in self._hits if h.key == key), None)


def _hit(entity_type, key, title):
    return SearchHit(
        entity_type=entity_type, entity_label=entity_type.title(),
        key=key, title=title, snippet="s", url=f"/{entity_type}/{key}",
    )


def test_register_and_search_aggregates_across_providers():
    registry = SearchProviderRegistry()
    registry.register(_FakeProvider("shop_product", "Shop", [_hit("shop_product", "mat", "Yoga Mat")]))
    registry.register(_FakeProvider("booking_resource", "Booking", [_hit("booking_resource", "room", "Yoga Room")]))

    hits = registry.search("yoga")

    assert {h.entity_type for h in hits} == {"shop_product", "booking_resource"}
    assert {h.title for h in hits} == {"Yoga Mat", "Yoga Room"}


def test_entity_types_filter_restricts_providers():
    registry = SearchProviderRegistry()
    registry.register(_FakeProvider("shop_product", "Shop", [_hit("shop_product", "mat", "Yoga Mat")]))
    registry.register(_FakeProvider("booking_resource", "Booking", [_hit("booking_resource", "room", "Yoga Room")]))

    hits = registry.search("yoga", entity_types=["shop_product"])

    assert [h.entity_type for h in hits] == ["shop_product"]


def test_blank_query_returns_no_hits():
    registry = SearchProviderRegistry()
    registry.register(_FakeProvider("shop_product", "Shop", [_hit("shop_product", "mat", "Yoga Mat")]))
    assert registry.search("") == []
    assert registry.search("   ") == []


def test_failing_provider_is_skipped_not_fatal():
    registry = SearchProviderRegistry()
    registry.register(_FakeProvider("shop_product", "Shop", raises=True))
    registry.register(_FakeProvider("booking_resource", "Booking", [_hit("booking_resource", "room", "Yoga Room")]))

    hits = registry.search("yoga")

    assert [h.entity_type for h in hits] == ["booking_resource"]


@pytest.mark.parametrize("blocked", sorted(GDPR_BLOCKED_ENTITY_TYPES))
def test_gdpr_entities_cannot_be_registered(blocked):
    registry = SearchProviderRegistry()
    with pytest.raises(ValueError):
        registry.register(_FakeProvider(blocked, blocked.title()))
    assert registry.get(blocked) is None


def test_get_detail_resolves_by_key():
    provider = _FakeProvider("shop_product", "Shop", [_hit("shop_product", "mat", "Yoga Mat")])
    registry = SearchProviderRegistry()
    registry.register(provider)
    detail = registry.get("shop_product").get_detail("mat")
    assert detail is not None and detail.title == "Yoga Mat"
    assert registry.get("shop_product").get_detail("nope") is None


def test_unregister_and_clear():
    registry = SearchProviderRegistry()
    registry.register(_FakeProvider("shop_product", "Shop"))
    registry.unregister("shop_product")
    assert registry.entity_types() == []
    registry.register(_FakeProvider("booking_resource", "Booking"))
    registry.clear()
    assert registry.all() == []
