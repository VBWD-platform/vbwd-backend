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
        # The argument may now be a callable (``lambda: get_auth_rate_limit(...)``)
        # whose inner call carries its own parens, so match non-greedily up to
        # the decorated def rather than a single paren-free group.
        login_block = re.search(
            r"@limiter\.limit\(.+?\)\s*\ndef login\(\)",
            source,
            re.DOTALL,
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
            r"@limiter\.limit\(.+?\)\s*\ndef register\(\)",
            source,
            re.DOTALL,
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

    def test_auth_routes_carry_beta_appropriate_limits(self):
        """S90 G5/D4 — the auth routes were tightened from the effectively
        unbounded ``5000 per minute`` to beta anti-abuse caps (owner-approved
        'Moderate' posture). The events webhook keeps its tighter 100/minute.
        These are the security-sensitive numbers that must not silently drift
        back up.

        The per-route caps are now externalised into the core rate-limits store
        (``${VBWD_VAR_DIR}/core/rate_limits.json`` with compiled defaults), so
        the contract lives in the store's values rather than in source-literal
        decorators. We still guard that each function carries a
        ``@limiter.limit(...)`` (now a callable into the store) and that the old
        unbounded value cannot creep back in.
        """
        from vbwd.services.core_rate_limits_store import get_auth_rate_limit

        # Each security-sensitive auth route + its approved per-minute cap. The
        # store values are the single source of truth for the caps.
        expected = {
            "register": "15 per minute",
            "login": "30 per minute",
            "check_email": "60 per minute",
            "forgot_password": "10 per minute",
            "reset_password": "10 per minute",
        }
        for func_name, limit in expected.items():
            assert get_auth_rate_limit(func_name) == limit, (
                f"/{func_name} must keep its beta cap {limit!r}, "
                f"found {get_auth_rate_limit(func_name)!r}."
            )

        here = os.path.dirname(os.path.abspath(__file__))
        backend = os.path.dirname(os.path.dirname(os.path.dirname(here)))

        auth_path = os.path.join(backend, "vbwd", "routes", "auth.py")
        with open(auth_path) as handle:
            auth_source = handle.read()

        # Each function must still carry a @limiter.limit(...) decorator
        # (presence guard) — now in the callable form reading the store, whose
        # inner call carries its own parens (matched non-greedily up to the def).
        for func_name in expected:
            block = re.search(
                r"@limiter\.limit\(.+?\)\s*\ndef " + func_name + r"\(\)",
                auth_source,
                re.DOTALL,
            )
            assert (
                block is not None
            ), f"POST/GET /{func_name} must stay decorated with @limiter.limit(...)."

        # No route may regress to the old unbounded 5000/minute value.
        assert (
            "5000 per minute" not in auth_source
        ), "auth routes must NOT carry the old unbounded 5000/minute override."

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
