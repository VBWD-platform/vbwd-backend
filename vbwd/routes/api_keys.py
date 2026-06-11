"""Core API-key self-service routes (S52).

A user holding the ``manage_api`` permission manages **their own** keys. Every
route is current-user-scoped + ``manage_api``-gated server-side (defence in
depth — FE gating is UX only) and owner-checked.
"""
from flask import Blueprint, g, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.api_key_auth import require_api_key
from vbwd.middleware.auth import require_auth, require_user_permission
from vbwd.repositories.api_key_repository import ApiKeyRepository
from vbwd.services.api_key_service import ApiKeyService
from vbwd.services.api_scope_registry import collect_user_grantable_scopes

api_keys_bp = Blueprint("api_keys", __name__, url_prefix="/api/v1/api-keys")


def _api_key_service() -> ApiKeyService:
    return ApiKeyService(ApiKeyRepository(db.session))


def _grantable_scope_keys() -> set:
    """Flatten the user-grantable scope catalogue into a set of scope keys."""
    catalog = collect_user_grantable_scopes()
    keys: set = set()
    for scopes in catalog.values():
        for scope in scopes:
            keys.add(scope["key"])
    return keys


@api_keys_bp.route("/health", methods=["GET"])
@require_api_key()
def api_key_health():
    """GET /api/v1/api-keys/health — verify an API key works (the test endpoint).

    Authenticated by the ``X-API-Key`` header (NOT a JWT). Any valid, active,
    IP-allowed key passes — **no scope required** — so a holder can confirm a
    key is live and see what it's allowed to do. The secret is never returned.
    """
    key = g.api_key
    return (
        jsonify(
            {
                "ok": True,
                "message": "API key is valid",
                "user_id": str(g.user_id),
                "key_prefix": key.key_prefix,
                "label": key.label,
                "scopes": list(key.scopes or []),
                "ip_whitelist": list(key.ip_whitelist or []),
            }
        ),
        200,
    )


@api_keys_bp.route("/scopes", methods=["GET"])
@require_auth
@require_user_permission("manage_api")
def list_grantable_scopes():
    """The scopes a user may self-grant on the Manage-API page."""
    return jsonify({"scopes": collect_user_grantable_scopes()}), 200


@api_keys_bp.route("", methods=["GET"])
@require_auth
@require_user_permission("manage_api")
def list_own_keys():
    """List the caller's own keys."""
    keys = _api_key_service().list_for_user(g.user_id)
    return jsonify({"api_keys": [key.to_dict() for key in keys]}), 200


@api_keys_bp.route("", methods=["POST"])
@require_auth
@require_user_permission("manage_api")
def create_own_key():
    """Create a key for the caller. Returns the plaintext token once.

    A user may only grant ``user_grantable`` scopes — any other requested
    scope is rejected (no privilege escalation).
    """
    data = request.get_json() or {}
    label = (data.get("label") or "").strip()
    if not label:
        return jsonify({"error": "label is required"}), 400

    requested_scopes = data.get("scopes") or []
    grantable = _grantable_scope_keys()
    forbidden = [scope for scope in requested_scopes if scope not in grantable]
    if forbidden:
        return (
            jsonify({"error": "Scope not self-grantable", "scopes": forbidden}),
            403,
        )

    service = _api_key_service()
    api_key, plaintext = service.generate(
        user_id=g.user_id,
        label=label,
        scopes=requested_scopes,
        ip_whitelist=data.get("ip_whitelist") or [],
        created_by_user_id=g.user_id,
    )
    result = api_key.to_dict()
    result["plaintext"] = plaintext
    return jsonify({"api_key": result}), 201


@api_keys_bp.route("/<key_id>/revoke", methods=["POST"])
@require_auth
@require_user_permission("manage_api")
def revoke_own_key(key_id):
    """Revoke one of the caller's own keys (owner-guarded)."""
    service = _api_key_service()
    try:
        revoked = service.revoke(key_id, owner_id=g.user_id)
    except PermissionError:
        return jsonify({"error": "Not found"}), 404
    if not revoked:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "API key revoked"}), 200


@api_keys_bp.route("/<key_id>", methods=["DELETE"])
@require_auth
@require_user_permission("manage_api")
def delete_own_key(key_id):
    """Delete one of the caller's own keys (owner-guarded)."""
    service = _api_key_service()
    api_key = service.get(key_id)
    if not api_key or str(api_key.user_id) != str(g.user_id):
        return jsonify({"error": "Not found"}), 404
    service.delete(key_id)
    return jsonify({"message": "API key deleted"}), 200
