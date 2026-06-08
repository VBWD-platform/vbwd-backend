"""Generic read-through cache (core infrastructure).

Public surface:
  - ``ICacheStore`` / ``InMemoryCacheStore`` / ``RedisCacheStore`` — the port + impls.
  - ``cached_response`` — a read-through helper that caches only successful 2xx
    JSON bodies, keyed by an opaque caller-supplied key.
  - ``resolve_cache_store`` — the single accessor consumers use; returns the
    process store (built from app config, Redis-backed when available), or an
    override installed for tests via ``set_cache_store``.

The module is domain-agnostic: it carries no knowledge of what is cached.
"""
import json
import logging
from typing import Callable, Optional, Tuple

from vbwd.services.cache.store import (
    ICacheStore,
    InMemoryCacheStore,
    RedisCacheStore,
)

__all__ = [
    "ICacheStore",
    "InMemoryCacheStore",
    "RedisCacheStore",
    "cached_response",
    "resolve_cache_store",
    "set_cache_store",
    "reset_cache_store",
    "DEFAULT_TTL_SECONDS",
]

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 120

_store_override: Optional[ICacheStore] = None
_default_store: Optional[ICacheStore] = None

JsonBody = dict
Producer = Callable[[], Tuple[JsonBody, int]]


def cached_response(
    store: ICacheStore,
    key: str,
    ttl: int,
    producer: Producer,
) -> Tuple[JsonBody, int]:
    """Read-through cache for a JSON response.

    Returns ``(body, status)``. On a hit, the cached body is returned with
    status 200. On a miss, ``producer`` runs; its result is cached **only** when
    the status is 2xx, then returned unchanged. A disabled store always calls
    the producer.
    """
    cached = store.get(key)
    if cached is not None:
        return json.loads(cached), 200

    body, status = producer()
    if 200 <= status < 300:
        try:
            store.set(key, json.dumps(body), ttl)
        except (TypeError, ValueError) as error:
            # Body is not JSON-serialisable — serve it, just don't cache it.
            logger.warning("cache skip (non-serialisable body): %s", error)
    return body, status


def _build_default_store() -> ICacheStore:
    """Build the process store from Flask config, Redis-backed when possible."""
    try:
        from flask import current_app

        config = current_app.config
        # Cache is off by default under TESTING so test runs are deterministic
        # (tests opt in via set_cache_store with an InMemoryCacheStore). In
        # every other environment it defaults on. An explicit CACHE_ENABLED
        # always wins.
        default_enabled = not config.get("TESTING", False)
        enabled = bool(config.get("CACHE_ENABLED", default_enabled))
        if not enabled:
            return InMemoryCacheStore(enabled=False)
        from vbwd.utils.redis_client import redis_client

        return RedisCacheStore(redis_client.client, enabled=True)
    except Exception as error:
        # No app context / no Redis — fall back to an in-memory store so callers
        # always get a working ICacheStore (degrades, never raises).
        logger.warning("cache store build failed, using in-memory: %s", error)
        return InMemoryCacheStore()


def resolve_cache_store() -> ICacheStore:
    """Return the active cache store (test override wins, else the process store)."""
    global _default_store
    if _store_override is not None:
        return _store_override
    if _default_store is None:
        _default_store = _build_default_store()
    return _default_store


def set_cache_store(store: ICacheStore) -> None:
    """Install a cache store (tests). Subsequent ``resolve_cache_store`` returns it."""
    global _store_override
    _store_override = store


def reset_cache_store() -> None:
    """Clear any installed override and the cached process store (tests)."""
    global _store_override, _default_store
    _store_override = None
    _default_store = None
