"""Core device-token routes (S66) — the S67.2 iOS wire contract.

POST /api/v1/devices/register (JWT auth) — idempotent upsert by token.
DELETE /api/v1/devices/<token> (JWT auth) — owner-only revoke.
"""
from flask import Blueprint, current_app, g, jsonify, request

from vbwd.middleware.auth import require_auth

device_tokens_bp = Blueprint("device_tokens", __name__, url_prefix="/api/v1/devices")


@device_tokens_bp.route("/register", methods=["POST"])
@require_auth
def register_device():
    """Register (upsert) the caller's device token → 201.

    Body: ``{token, platform: "ios", bundle_id, app}``. Idempotent: the same
    token re-registers in place (latest user wins, ``last_seen_at`` refreshed).
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    platform = (data.get("platform") or "").strip()
    bundle_id = (data.get("bundle_id") or "").strip()
    app_name = (data.get("app") or "").strip()

    if not token:
        return jsonify({"error": "token is required"}), 400
    if not bundle_id:
        return jsonify({"error": "bundle_id is required"}), 400
    if not app_name:
        return jsonify({"error": "app is required"}), 400

    service = current_app.container.device_token_service()
    try:
        row = service.register(
            user_id=g.user_id,
            token=token,
            platform=platform,
            bundle_id=bundle_id,
            app=app_name,
        )
    except ValueError as error:
        # Covers UnsupportedPlatformError + empty-token guards in the service.
        return jsonify({"error": str(error)}), 400
    return jsonify({"device": row.to_dict()}), 201


@device_tokens_bp.route("/<token>", methods=["DELETE"])
@require_auth
def unregister_device(token):
    """Revoke one of the caller's own device tokens → 204 (owner-only)."""
    service = current_app.container.device_token_service()
    row = service.find_by_token(token)
    if row is None:
        return jsonify({"error": "Not found"}), 404
    if str(row.user_id) != str(g.user_id):
        return jsonify({"error": "Forbidden"}), 403
    service.unregister(token)
    return "", 204
