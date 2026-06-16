"""Debug-endpoint gate (S30).

The load-test introspection endpoints (``/api/v1/_routes`` and
``/api/v1/_seed_status``) expose information an attacker would value
(route catalog = fuzzing recon). They are therefore hidden behind a single
boolean config flag, defaulting OFF so production images are safe. CI / dev
opt in via ``VBWD_ENABLE_DEBUG_ENDPOINTS=1`` (mapped to the
``ENABLE_DEBUG_ENDPOINTS`` Flask config key in the app factory).

Both endpoints share this one decorator (DRY) instead of each re-reading the
flag. The flag is read at REQUEST time, not at import/boot, so a pytest
fixture can flip ``app.config["ENABLE_DEBUG_ENDPOINTS"]`` per test.
"""
from functools import wraps

from flask import abort, current_app

DEBUG_ENDPOINTS_CONFIG_KEY = "ENABLE_DEBUG_ENDPOINTS"


def require_debug_enabled(view_func):
    """Hide a route unless debug endpoints are explicitly enabled.

    Returns ``404`` (not ``403``) when disabled so the endpoint is
    indistinguishable from a non-existent route to an unauthenticated probe.
    """

    @wraps(view_func)
    def decorated_view(*args, **kwargs):
        if current_app.config.get(DEBUG_ENDPOINTS_CONFIG_KEY) is not True:
            abort(404)
        return view_func(*args, **kwargs)

    # S90 — let the route-exposure oracle recognise a debug-gated route via an
    # introspectable marker (mirrors the requires_auth/required_permission
    # markers in middleware/auth.py) instead of re-parsing source. A
    # debug-gated route is hidden (404) in production, so the oracle treats the
    # marker as a distinct, acceptable protection class.
    decorated_view.requires_debug_enabled = True  # type: ignore[attr-defined]
    return decorated_view
