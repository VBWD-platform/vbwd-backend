"""Generic read-through cache store (core infrastructure).

A narrow, domain-agnostic key/value cache behind a single interface. Callers
build opaque string keys; the store knows nothing about what is cached. Two
implementations ship:

  - ``RedisCacheStore`` — backed by the shared Redis connection, with graceful
    degradation: any Redis failure becomes a cache miss (read) or a no-op
    (write/clear), so a Redis outage never turns a working read into a 500.
  - ``InMemoryCacheStore`` — a process-local dict with TTL, for unit tests and
    for environments without Redis.

Values are stored as already-serialised strings; serialisation policy lives
with the caller / helper, not here.
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ICacheStore(ABC):
    """Minimal cache port: opaque-key get / set / prefix-clear."""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Return the stored string for ``key`` or ``None`` on miss."""

    @abstractmethod
    def set(self, key: str, value: str, ttl: int) -> None:
        """Store ``value`` under ``key`` for ``ttl`` seconds."""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """Remove every key beginning with ``prefix``."""

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """Whether reads/writes are active (disabled = always-miss passthrough)."""


class InMemoryCacheStore(ICacheStore):
    """Process-local dict cache with TTL. Test/dev fallback impl."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        # key -> (value, expires_at_epoch_seconds)
        self._entries: Dict[str, Tuple[str, float]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get(self, key: str) -> Optional[str]:
        if not self._enabled:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl: int) -> None:
        if not self._enabled:
            return
        self._entries[key] = (value, time.monotonic() + ttl)

    def delete_prefix(self, prefix: str) -> None:
        for key in [k for k in self._entries if k.startswith(prefix)]:
            self._entries.pop(key, None)


class RedisCacheStore(ICacheStore):
    """Redis-backed cache. Degrades to always-miss on any Redis failure."""

    def __init__(self, redis_connection, enabled: bool = True, namespace: str = "rc"):
        self._redis = redis_connection
        self._enabled = enabled
        self._namespace = namespace

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _namespaced(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    def get(self, key: str) -> Optional[str]:
        if not self._enabled:
            return None
        try:
            return self._redis.get(self._namespaced(key))
        except Exception as error:
            # Degrade to a cache miss — a Redis outage must never 500 a read.
            logger.warning("cache get failed (degrading to miss): %s", error)
            return None

    def set(self, key: str, value: str, ttl: int) -> None:
        if not self._enabled:
            return
        try:
            self._redis.set(self._namespaced(key), value, ex=ttl)
        except Exception as error:
            # A write failure is harmless — the next read just goes to the DB.
            logger.warning("cache set failed (skipping): %s", error)

    def delete_prefix(self, prefix: str) -> None:
        if not self._enabled:
            return
        pattern = f"{self._namespaced(prefix)}*"
        try:
            keys = list(self._redis.scan_iter(match=pattern))
            if keys:
                self._redis.delete(*keys)
        except Exception as error:
            # Clearing failed — the short TTL is the backstop for staleness.
            logger.warning("cache delete_prefix failed (skipping): %s", error)
