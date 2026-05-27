"""Tests for rate limiting on authentication routes.

S18 — removed 4 ``@pytest.mark.skip`` tests that tried to exhaust the
production rate limits (``5000 per minute`` on /login, etc.) in a tight
unit-test loop. Flask-Limiter limits are baked into the decorator at
import time, so per-test threshold overrides aren't viable; the
"rate-limit actually trips" behaviour belongs in flask-limiter's own
test suite (and an integration test against real Redis if we want
end-to-end coverage — see Sprint S18's deferred E2E note).

What we KEEP and verify here:
  - Requests under the limit pass through to the route logic.
  - The limiter is configured + enabled in the test app.
  - Per-route limit DECLARATIONS exist on the security-sensitive
    endpoints (a static guard against accidentally removing
    ``@limiter.limit(...)`` from /login or /register).

What we DROPPED (and why): the four skipped tests were
coverage theatre — they always passed (because they were skipped) but
asserted nothing real. §7 clean code: remove dead tests rather than
keep them as scaffolding.
"""
import os
import re


class TestRateLimitingUnderLimit:
    """Verifies the route layer behaves normally for requests under the
    rate-limit threshold."""

    def test_register_allows_requests_under_limit(self, client):
        """Register allows requests under the rate limit (validation
        failures should be 400, not 429)."""
        for sequence_number in range(2):
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"test{sequence_number}@example.com",
                    "password": "WeakPass",  # validation failure, not limit
                },
            )
            assert response.status_code == 400


class TestRateLimitingConfiguration:
    """Static guards that rate limiting stays configured + applied to the
    security-sensitive routes."""

    def test_limiter_is_configured(self, app):
        from vbwd.extensions import limiter

        assert limiter is not None

    def test_limiter_is_enabled(self, app):
        from vbwd.extensions import limiter

        assert limiter.enabled is True

    def test_login_route_has_rate_limit_decorator(self):
        """A regression guard: never accidentally remove the limiter
        from /login."""
        here = os.path.dirname(os.path.abspath(__file__))
        backend = os.path.dirname(os.path.dirname(os.path.dirname(here)))
        auth_path = os.path.join(backend, "vbwd", "routes", "auth.py")
        with open(auth_path) as handle:
            source = handle.read()
        # locate the login route + assert a @limiter.limit decorator is on it.
        login_block = re.search(
            r"(@limiter\.limit\([^\)]+\)\s*\n)+\s*def login\(\)",
            source,
        )
        assert (
            login_block is not None
        ), "POST /login MUST stay decorated with @limiter.limit(...)."

    def test_register_route_has_rate_limit_decorator(self):
        """Same guard for /register."""
        here = os.path.dirname(os.path.abspath(__file__))
        backend = os.path.dirname(os.path.dirname(os.path.dirname(here)))
        auth_path = os.path.join(backend, "vbwd", "routes", "auth.py")
        with open(auth_path) as handle:
            source = handle.read()
        register_block = re.search(
            r"(@limiter\.limit\([^\)]+\)\s*\n)+\s*def register\(\)",
            source,
        )
        assert (
            register_block is not None
        ), "POST /register MUST stay decorated with @limiter.limit(...)."
