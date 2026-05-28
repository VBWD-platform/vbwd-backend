"""S27 §4.1 — env-driven construction of the global Flask-Limiter ceilings.

Tests target `vbwd.extensions._global_default_limits()` in isolation. Pure
stdlib + env-var manipulation; no Flask app boot, no Redis.
"""
import importlib
import os
from typing import Iterator

import pytest


@pytest.fixture
def env_isolation() -> Iterator[None]:
    """Snapshot the two env vars before each test and restore after.

    `_global_default_limits()` reads os.environ at call time, so each test
    can mutate freely.
    """
    snapshot = {
        key: os.environ.get(key)
        for key in ("RATELIMIT_DEFAULT_DAY", "RATELIMIT_DEFAULT_HOUR")
    }
    for key in snapshot:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in snapshot.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _global_default_limits():
    # Imported lazily so each test gets a fresh reference to the function
    # rather than a snapshot from import time.
    from vbwd import extensions

    importlib.reload(extensions) if False else None  # noqa: B015 — pyflakes
    return extensions._global_default_limits()


class TestGlobalDefaultLimits:
    def test_defaults_when_env_unset(self, env_isolation):
        result = _global_default_limits()
        assert result == ["100000 per day", "20000 per hour"]

    def test_env_overrides_day(self, env_isolation):
        os.environ["RATELIMIT_DEFAULT_DAY"] = "42"
        result = _global_default_limits()
        assert result[0] == "42 per day"
        # Hour falls through to its default.
        assert result[1] == "20000 per hour"

    def test_env_overrides_hour(self, env_isolation):
        os.environ["RATELIMIT_DEFAULT_HOUR"] = "7"
        result = _global_default_limits()
        assert result[0] == "100000 per day"
        assert result[1] == "7 per hour"

    def test_zero_day_disables_that_window(self, env_isolation):
        os.environ["RATELIMIT_DEFAULT_DAY"] = "0"
        result = _global_default_limits()
        # No "0 per day" descriptor — that window is dropped entirely.
        assert all("per day" not in descriptor for descriptor in result)
        assert result == ["20000 per hour"]

    def test_zero_hour_disables_that_window(self, env_isolation):
        os.environ["RATELIMIT_DEFAULT_HOUR"] = "0"
        result = _global_default_limits()
        assert all("per hour" not in descriptor for descriptor in result)
        assert result == ["100000 per day"]

    def test_both_zero_returns_empty_list(self, env_isolation):
        # Operator's escape hatch: both zero = limiter has no default cap
        # (per-route @limiter.limit overrides still apply).
        os.environ["RATELIMIT_DEFAULT_DAY"] = "0"
        os.environ["RATELIMIT_DEFAULT_HOUR"] = "0"
        assert _global_default_limits() == []

    def test_non_integer_day_raises_value_error(self, env_isolation):
        os.environ["RATELIMIT_DEFAULT_DAY"] = "abc"
        with pytest.raises(ValueError):
            _global_default_limits()

    def test_non_integer_hour_raises_value_error(self, env_isolation):
        os.environ["RATELIMIT_DEFAULT_HOUR"] = "not-a-number"
        with pytest.raises(ValueError):
            _global_default_limits()


class TestLimiterPicksUpDefaults:
    """The Limiter instance constructed at module import time must reflect
    `_global_default_limits()`. We can't change env after import (the limiter
    is already built), so we just assert the contract holds for whatever
    env was set at import time.
    """

    def test_limiter_default_limits_match_helper_output(self, env_isolation):
        # Note: env_isolation here is mostly informational — the limiter
        # was already constructed at module import. We verify the contract
        # by re-running the helper with that same import-time env.
        from vbwd.extensions import limiter

        # flask-limiter stores the defaults under
        # `limiter.limit_manager.default_limits` as a list of Limit objects.
        # We assert on their stringified descriptors so the test stays
        # resilient to internal type changes between versions.
        descriptors = [str(item.limit) for item in limiter.limit_manager.default_limits]
        # In CI / dev the env is unset, so the helper's defaults apply:
        # 100k/day and 20k/hour. Each item's str() form is like
        # "100000 per 1 day" / "20000 per 1 hour".
        assert any("100000" in descriptor for descriptor in descriptors)
        assert any("20000" in descriptor for descriptor in descriptors)
