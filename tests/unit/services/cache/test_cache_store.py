"""S48.2 oracle — generic core cache store + cached-response helper.

The cache port is domain-agnostic infrastructure: ``get`` / ``set`` /
``delete_prefix`` keyed by opaque strings. It knows nothing about plans,
addons or bundles — callers (the subscription plugin, the core token-bundle
route) build their own keys. These tests pin:

  - a second identical request is served from cache (the producer runs once);
  - a different key (e.g. a different currency) is an independent entry;
  - ``delete_prefix`` clears a whole key family → next read repopulates;
  - TTL expiry repopulates;
  - non-2xx responses are never cached;
  - when the store is disabled, every read goes to the producer.
"""
import time

import pytest

from vbwd.services.cache import (
    ICacheStore,
    InMemoryCacheStore,
    cached_response,
)


def test_inmemory_store_is_an_icachestore():
    assert isinstance(InMemoryCacheStore(), ICacheStore)


def test_set_then_get_returns_value():
    store = InMemoryCacheStore()
    store.set("k", "v", ttl=60)
    assert store.get("k") == "v"


def test_get_missing_key_returns_none():
    assert InMemoryCacheStore().get("absent") is None


def test_delete_prefix_clears_matching_keys_only():
    store = InMemoryCacheStore()
    store.set("tarif-plans:EUR", "a", ttl=60)
    store.set("tarif-plans:USD", "b", ttl=60)
    store.set("token-bundles:EUR", "c", ttl=60)

    store.delete_prefix("tarif-plans:")

    assert store.get("tarif-plans:EUR") is None
    assert store.get("tarif-plans:USD") is None
    assert store.get("token-bundles:EUR") == "c"


def test_ttl_expiry_drops_the_entry():
    store = InMemoryCacheStore()
    store.set("k", "v", ttl=1)
    assert store.get("k") == "v"
    time.sleep(1.1)
    assert store.get("k") is None


def test_cached_response_serves_second_call_from_cache():
    """The producer runs exactly once for two identical reads."""
    store = InMemoryCacheStore()
    calls = {"count": 0}

    def producer():
        calls["count"] += 1
        return {"plans": ["a"]}, 200

    body1, status1 = cached_response(store, "tarif-plans:EUR", 60, producer)
    body2, status2 = cached_response(store, "tarif-plans:EUR", 60, producer)

    assert (body1, status1) == ({"plans": ["a"]}, 200)
    assert (body2, status2) == ({"plans": ["a"]}, 200)
    assert calls["count"] == 1


def test_cached_response_different_key_is_independent():
    store = InMemoryCacheStore()
    calls = {"count": 0}

    def producer():
        calls["count"] += 1
        return {"currency": calls["count"]}, 200

    cached_response(store, "tarif-plans:EUR", 60, producer)
    cached_response(store, "tarif-plans:USD", 60, producer)

    assert calls["count"] == 2


def test_cached_response_repopulates_after_delete_prefix():
    store = InMemoryCacheStore()
    calls = {"count": 0}

    def producer():
        calls["count"] += 1
        return {"n": calls["count"]}, 200

    cached_response(store, "tarif-plans:EUR", 60, producer)
    store.delete_prefix("tarif-plans:")
    body, status = cached_response(store, "tarif-plans:EUR", 60, producer)

    assert calls["count"] == 2
    assert body == {"n": 2}


def test_cached_response_does_not_cache_non_2xx():
    store = InMemoryCacheStore()
    calls = {"count": 0}

    def producer():
        calls["count"] += 1
        return {"error": "not found"}, 404

    cached_response(store, "tarif-plans:bad", 60, producer)
    cached_response(store, "tarif-plans:bad", 60, producer)

    assert calls["count"] == 2
    assert store.get("tarif-plans:bad") is None


def test_disabled_store_always_calls_producer():
    store = InMemoryCacheStore(enabled=False)
    calls = {"count": 0}

    def producer():
        calls["count"] += 1
        return {"plans": []}, 200

    cached_response(store, "tarif-plans:EUR", 60, producer)
    cached_response(store, "tarif-plans:EUR", 60, producer)

    assert calls["count"] == 2


def test_cache_port_has_no_catalogue_vocabulary():
    """Agnosticism: the cache module names no plan/addon/bundle domain term."""
    import inspect

    import vbwd.services.cache as cache_pkg
    from vbwd.services.cache import store as store_mod

    forbidden = ("plan", "addon", "bundle", "subscription", "tarif", "catalog")
    for module in (cache_pkg, store_mod):
        source = inspect.getsource(module).lower()
        for term in forbidden:
            assert term not in source, f"{module.__name__} mentions '{term}'"


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_cached_response_caches_any_2xx(status):
    store = InMemoryCacheStore()
    calls = {"count": 0}

    def producer():
        calls["count"] += 1
        return {"ok": True}, status

    cached_response(store, f"k:{status}", 60, producer)
    cached_response(store, f"k:{status}", 60, producer)

    assert calls["count"] == 1
