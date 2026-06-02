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


class TestS27NoRegression:
    """S27 lifted the global default ceilings + made them env-driven. These
    specs pin the contracts that must NOT regress: existing per-route
    overrides are intact, the 429 body shape is untouched, and the test-
    harness `RATELIMIT_ENABLED: False` toggle still disables the limiter.
    """

    def test_existing_per_route_overrides_unchanged(self):
        """Auth routes carry 5000/minute (looser brute-force tolerance) and
        the events webhook keeps 100/minute (tighter). Both are independent
        of the global default lift in S27.
        """
        here = os.path.dirname(os.path.abspath(__file__))
        backend = os.path.dirname(os.path.dirname(os.path.dirname(here)))

        auth_path = os.path.join(backend, "vbwd", "routes", "auth.py")
        with open(auth_path) as handle:
            auth_source = handle.read()
        assert (
            '@limiter.limit("5000 per minute")' in auth_source
        ), "auth routes must keep their 5000/minute override (brute-force tolerance)."

        events_path = os.path.join(backend, "vbwd", "routes", "events.py")
        with open(events_path) as handle:
            events_source = handle.read()
        assert (
            '@limiter.limit("100 per minute")' in events_source
        ), "events webhook must keep its tighter 100/minute cap."

    def test_429_response_shape_unchanged(self):
        """Prod clients (fe-user web + iOS) parse the 429 body shape. S27
        only changes the *numbers*; the shape stays `{"error": "...",
        "message": "..."}` and `Retry-After` keeps being parsed from the
        descriptor at vbwd/app.py:ratelimit_handler.
        """
        here = os.path.dirname(os.path.abspath(__file__))
        backend = os.path.dirname(os.path.dirname(os.path.dirname(here)))
        app_path = os.path.join(backend, "vbwd", "app.py")
        with open(app_path) as handle:
            source = handle.read()
        assert (
            '"error": "Rate limit exceeded"' in source
        ), "The 429 body must keep its `error` field for client parsers."
        assert (
            '"message": str(error.description)' in source
        ), "The 429 body must keep its `message` field for client parsers."
        # Retry-After parsing block exists.
        assert (
            'response.headers["Retry-After"]' in source or "Retry-After" in source
        ), "Retry-After parsing must stay in ratelimit_handler."

    def test_ratelimit_enabled_false_still_disables(self):
        """Every plugin conftest passes `RATELIMIT_ENABLED: False` to keep
        unit tests from accidentally tripping the global limiter. S27 must
        not break that toggle. We build a fresh app here (rather than using
        the shared `app` fixture which sets it to True) so this test is
        independent of the fixture's defaults.
        """
        from vbwd.app import create_app
        from vbwd.config import get_database_url
        from vbwd.extensions import limiter

        app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": get_database_url(),
                "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                "RATELIMIT_ENABLED": False,
                "RATELIMIT_STORAGE_URL": "memory://",
            }
        )

        assert app.config.get("RATELIMIT_ENABLED") is False
        # flask-limiter mirrors the app-config toggle into limiter.enabled
        # after init_app. The toggle path must survive S27's env-driven
        # default lift.
        assert limiter.enabled is False


class TestRateLimitTelemetry:
    """S33 — every 429 emitted by the global Flask-Limiter handler writes a
    single WARN-level structured log line so the next "users hit the cap"
    report is answerable with grep instead of guesswork."""

    def test_429_emits_warn_log_with_route_key_descriptor(self, app, caplog):
        """A 429 routed through `vbwd/app.py:ratelimit_handler` emits one WARN
        line carrying the route, the bucket key, and the tripped descriptor.

        We drive the real registered 429 handler via `handle_http_exception`
        inside a request context — exercising `ratelimit_handler` end-to-end
        without hammering a live limit or depending on URL-map ordering.
        """
        import logging

        from werkzeug.exceptions import TooManyRequests

        with app.test_request_context("/api/v1/some-limited-route"):
            error = TooManyRequests(description="5 per 1 minute")
            with caplog.at_level(logging.WARNING):
                response = app.handle_http_exception(error)

        assert response.status_code == 429
        assert "429 route=" in caplog.text, caplog.text
        # bucket key (current keyfunc is get_remote_address → the request IP)
        assert "key=" in caplog.text
        # the tripped descriptor is carried through verbatim
        assert "5 per 1 minute" in caplog.text
