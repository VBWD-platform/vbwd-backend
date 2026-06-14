"""S48.2 — the public token-bundle list is served through the core cache.

These pin the core (token-bundle) half of the catalogue cache: the list route
caches its 2xx body, a second call is served from cache (no second repo query),
and ``invalidate_token_bundle_cache`` (called by every admin bundle write)
clears the prefix so the next read re-queries.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from vbwd.services.cache import (
    InMemoryCacheStore,
    set_cache_store,
    reset_cache_store,
)
from vbwd.routes.token_bundles import (
    TOKEN_BUNDLES_LIST_CACHE_KEY,
    invalidate_token_bundle_cache,
)


@pytest.fixture
def cache():
    store = InMemoryCacheStore(enabled=True)
    set_cache_store(store)
    yield store
    reset_cache_store()


def _fake_bundle(name):
    bundle = MagicMock()
    bundle.to_dict.return_value = {"id": str(uuid4()), "name": name}
    return bundle


# These tests pin the caching contract, not pricing. Stub the S85.2 Price
# enrichment so the route does not need a seeded currency / Priceable bundle.
@patch(
    "vbwd.routes.token_bundles._bundle_dict_with_price",
    side_effect=lambda bundle: bundle.to_dict(),
)
@patch("vbwd.routes.token_bundles.TokenBundleRepository")
def test_second_list_call_is_served_from_cache(
    mock_repo_cls, _mock_price, app, client, cache
):
    mock_repo_cls.return_value.find_active.return_value = [_fake_bundle("Starter")]

    first = client.get("/api/v1/token-bundles/")
    second = client.get("/api/v1/token-bundles/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json() == second.get_json()
    # The repository was queried exactly once — the second read hit the cache.
    assert mock_repo_cls.return_value.find_active.call_count == 1
    assert cache.get(TOKEN_BUNDLES_LIST_CACHE_KEY) is not None


@patch(
    "vbwd.routes.token_bundles._bundle_dict_with_price",
    side_effect=lambda bundle: bundle.to_dict(),
)
@patch("vbwd.routes.token_bundles.TokenBundleRepository")
def test_invalidation_forces_requery(mock_repo_cls, _mock_price, app, client, cache):
    mock_repo_cls.return_value.find_active.return_value = [_fake_bundle("Starter")]

    client.get("/api/v1/token-bundles/")
    with app.app_context():
        invalidate_token_bundle_cache()
    client.get("/api/v1/token-bundles/")

    assert mock_repo_cls.return_value.find_active.call_count == 2
