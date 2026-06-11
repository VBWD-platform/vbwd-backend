"""Core admin API-key routes (S52).

An admin holding ``api_keys.manage`` manages **any** user's keys and may grant
**any** registered scope.
"""
from flask import Blueprint, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.models.user import User
from vbwd.repositories.api_key_repository import ApiKeyRepository
from vbwd.services.api_key_service import ApiKeyService
from vbwd.services.api_scope_registry import collect_api_scopes

admin_api_keys_bp = Blueprint("admin_api_keys", __name__, url_prefix="/api/v1/admin")


def _api_key_service() -> ApiKeyService:
    return ApiKeyService(ApiKeyRepository(db.session))


@admin_api_keys_bp.route("/api-keys/scopes", methods=["GET"])
@require_auth
@require_permission("api_keys.manage")
def list_scopes():
    """Full scope catalogue for the admin tab (admins may grant any scope)."""
    return jsonify({"scopes": collect_api_scopes()}), 200


@admin_api_keys_bp.route("/users/<user_id>/api-keys", methods=["GET"])
@require_auth
@require_permission("api_keys.manage")
def list_user_keys(user_id):
    """List a target user's keys."""
    user = db.session.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    keys = _api_key_service().list_for_user(user_id)
    return jsonify({"api_keys": [key.to_dict() for key in keys]}), 200


@admin_api_keys_bp.route("/users/<user_id>/api-keys", methods=["POST"])
@require_auth
@require_permission("api_keys.manage")
def create_user_key(user_id):
    """Create a key for a target user. Returns the plaintext token once."""
    from flask import g

    user = db.session.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    label = (data.get("label") or "").strip()
    if not label:
        return jsonify({"error": "label is required"}), 400

    api_key, plaintext = _api_key_service().generate(
        user_id=user_id,
        label=label,
        scopes=data.get("scopes") or [],
        ip_whitelist=data.get("ip_whitelist") or [],
        created_by_user_id=g.user_id,
    )
    result = api_key.to_dict()
    result["plaintext"] = plaintext
    return jsonify({"api_key": result}), 201


@admin_api_keys_bp.route("/api-keys/<key_id>/revoke", methods=["POST"])
@require_auth
@require_permission("api_keys.manage")
def revoke_key(key_id):
    """Revoke any user's key."""
    if not _api_key_service().revoke(key_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "API key revoked"}), 200


@admin_api_keys_bp.route("/api-keys/<key_id>", methods=["DELETE"])
@require_auth
@require_permission("api_keys.manage")
def delete_key(key_id):
    """Delete any user's key."""
    if not _api_key_service().delete(key_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "API key deleted"}), 200
