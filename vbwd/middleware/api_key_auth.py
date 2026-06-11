"""Core API-key authentication guard (S52).

``require_api_key(scope)`` authenticates a request by its ``X-API-Key`` header
against the core ``ApiKeyService``, enforces the key's IP whitelist (before
scope) and the required scope, then — **Liskov-substitutable for
``require_auth``** — sets ``g.user_id`` AND ``g.user`` so ``require_permission``
and every downstream handler are auth-mechanism-agnostic.

Security:
- The plaintext token is never logged.
- Revocation is immediate (``is_active`` is checked on every request, inside
  ``ApiKeyService.verify``).
- ``X-Forwarded-For`` is honoured only when the app is configured to trust a
  proxy (``TRUST_FORWARDED_FOR``); otherwise the socket peer (``remote_addr``)
  is used.
"""
from functools import wraps
from typing import Optional

from flask import current_app, g, jsonify, request

from vbwd.extensions import db
from vbwd.repositories.api_key_repository import ApiKeyRepository
from vbwd.repositories.user_repository import UserRepository
from vbwd.services.api_key_service import ApiKeyService

API_KEY_HEADER = "X-API-Key"


def _resolve_api_key_service() -> ApiKeyService:
    """Build the service from the request-scoped session (swappable in tests)."""
    return ApiKeyService(ApiKeyRepository(db.session))


def _load_user(user_id):
    """Load the owning user (swappable in tests)."""
    return UserRepository(db.session).find_by_id(user_id)


def _client_ip() -> str:
    """Resolve the caller's IP, honouring forwarded-for only behind a proxy."""
    if current_app.config.get("TRUST_FORWARDED_FOR"):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def require_api_key(scope: Optional[str] = None):
    """Require a valid, IP-allowed API key for a route (optionally scoped).

    Args:
        scope: the opaque scope string the endpoint demands (a plugin-defined
            value like ``"<plugin>:<resource>:<action>"``). Core never
            interprets it — it only string-matches the key's allow-list. When
            ``None`` (the default), **no scope is required** — any valid,
            active, IP-allowed key passes. Used by the key-health endpoint so a
            holder can verify a key works regardless of its scopes.

    Returns:
        401 when the key is missing / unknown / inactive; 403 when the IP is
        not whitelisted or (when a scope is required) the scope is absent.
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            presented = request.headers.get(API_KEY_HEADER)
            if not presented:
                return jsonify({"error": "API key is required"}), 401

            service = _resolve_api_key_service()
            api_key = service.verify(presented)
            if api_key is None:
                return jsonify({"error": "Invalid or inactive API key"}), 401

            if not service.is_ip_allowed(api_key, _client_ip()):
                return jsonify({"error": "IP not allowed"}), 403

            if scope is not None and not service.has_scope(api_key, scope):
                return jsonify({"error": "Scope not granted", "required": scope}), 403

            service.touch(api_key)

            # Liskov parity with require_auth: downstream code reads g.user_id /
            # g.user without caring which mechanism authenticated the request.
            # g.api_key exposes the authenticating key (e.g. the health route).
            g.user_id = api_key.user_id
            g.user = _load_user(api_key.user_id)
            g.api_key = api_key

            return f(*args, **kwargs)

        # S30 — surface this route as authenticated to the route catalogue.
        decorated_function.requires_auth = True  # type: ignore[attr-defined]
        return decorated_function

    return decorator
