"""Secret redaction for the unified logging layer (Sprint 58.5, Security #6).

Before any log extra or event payload reaches disk, values whose key matches a
case-insensitive denylist are masked to ``"***"``. The pass recurses into nested
dicts and lists so a secret buried in a payload (e.g. ``{"nested":
{"client_secret": …}}``) is still masked. The input is never mutated — a cleaned
copy is returned.

The denylist intentionally covers the credential-shaped keys the platform emits
(auth tokens, passwords, API/private keys, OAuth client secrets, SMTP
passwords). The ``secrets/`` filesystem namespace (D4) holds the actual secret
*files*; those are never logged, so this guard only has to catch secrets that
leak into a structured payload.
"""
from __future__ import annotations

from typing import Any

MASK = "***"

# Case-insensitive substring denylist: a key whose lower-cased form contains any
# of these is redacted. Substring (not exact) so ``user_password`` /
# ``X-Api-Key`` style variants are caught too.
_DENYLIST_KEYS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "smtp_password",
    "client_secret",
    "access_token",
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(needle in lowered for needle in _DENYLIST_KEYS)


def redact(value: Any) -> Any:
    """Return a deep copy of *value* with secret-named keys masked to ``***``.

    Recurses through dicts and lists; scalars (and non-secret values) pass
    through unchanged. The original object is left untouched.
    """
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_secret_key(key):
                cleaned[key] = MASK
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value
