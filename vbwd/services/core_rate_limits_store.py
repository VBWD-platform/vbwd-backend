"""File-backed store for the core auth-route rate limits.

Generic core infrastructure — names no plugin domain. The per-route
anti-abuse caps for the security-sensitive ``/api/v1/auth/*`` endpoints are
read from a single JSON file at ``${VBWD_VAR_DIR:-/app/var}/core/rate_limits.json``.
The ``var/`` directory is host-mounted into the backend, so an operator can
tune the caps WITHOUT rebuilding the image (the values are no longer baked into
``vbwd/routes/auth.py`` as decorator literals).

``DEFAULT_AUTH_RATE_LIMITS`` is the compiled fallback / single source of truth
for the schema: only these known keys are honoured from the file, missing keys
fall back to their default, and a missing / corrupt / non-object file degrades
to defaults (logged) and never raises. Mirrors the IO contract of
``vbwd/services/core_settings_store.py``.

The auth blueprint passes a zero-arg callable into ``@limiter.limit(...)`` that
reads this store at request time, so a deployment can edit the file and have the
new cap take effect without a redeploy.
"""
import logging
from typing import Dict

from vbwd.services.filesystem import LocalFilesystemManager

logger = logging.getLogger(__name__)

# Single source of truth for the auth rate-limit schema + the compiled
# fallback caps (S90 G5/D4 "Moderate" beta posture). A key present here is the
# only key honoured from the override file.
DEFAULT_AUTH_RATE_LIMITS: Dict[str, str] = {
    "register": "15 per minute",
    "login": "30 per minute",
    "check_email": "60 per minute",
    "forgot_password": "10 per minute",
    "reset_password": "10 per minute",
}

# The core namespace stores ``${VBWD_VAR_DIR}/core/rate_limits.json``.
_CORE_NAMESPACE = "core"
_RATE_LIMITS_FILE = "rate_limits.json"


def _manager() -> LocalFilesystemManager:
    """Return a FilesystemManager bound to the current ``VBWD_VAR_DIR``.

    Built per call (cheaply) so an env change between requests — and the test
    harness's per-test ``monkeypatch.setenv("VBWD_VAR_DIR", ...)`` — is honoured.
    """
    return LocalFilesystemManager()


def get_auth_rate_limits() -> Dict[str, str]:
    """Return the per-route auth rate-limit caps merged over the defaults.

    File values override the defaults for known keys only. A missing or corrupt
    or non-object file degrades to the defaults (logged) and never raises.
    """
    loaded = _manager().read_json(_CORE_NAMESPACE, _RATE_LIMITS_FILE, default=None)
    if loaded is not None and not isinstance(loaded, dict):
        logger.warning(
            "Core rate-limits file %s/%s is not a JSON object; using defaults.",
            _CORE_NAMESPACE,
            _RATE_LIMITS_FILE,
        )
        loaded = None

    merged = dict(DEFAULT_AUTH_RATE_LIMITS)
    if isinstance(loaded, dict):
        for key in DEFAULT_AUTH_RATE_LIMITS:
            if key in loaded:
                merged[key] = loaded[key]
    return merged


def get_auth_rate_limit(name: str) -> str:
    """Return the cap string for a single auth route (default on absence)."""
    return get_auth_rate_limits().get(name, DEFAULT_AUTH_RATE_LIMITS[name])
