"""Client license routes — status + self-serve key add/remove.

Core, agnostic admin surface: it verifies/stores pasted keys and returns
whatever keys exist — it names no product or feature. Two ways to add a key:
paste an offline envelope (verified locally) or redeem a dashboard code (the
hub mints an instance-bound envelope, then the same local verify+store runs).
Gated with ``license.view`` / ``license.manage`` (seeded via the RBAC catalog).
"""
from flask import Blueprint, current_app, jsonify, request

from vbwd.middleware.auth import require_auth, require_permission
from vbwd.security.licensing.license_context import LicenseNotConfigured
from vbwd.security.licensing.license_store import LicenseKeyRejected
from vbwd.security.licensing.ports import LicenseActivationError

admin_license_bp = Blueprint(
    "admin_license", __name__, url_prefix="/api/v1/admin/license"
)

_HTTP_CREATED = 201
_HTTP_BAD_REQUEST = 400
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409
_HTTP_UNPROCESSABLE = 422
_HTTP_BAD_GATEWAY = 502


def _license_context():
    return getattr(current_app, "license_context", None)


@admin_license_bp.route("", methods=["GET"])
@require_auth
@require_permission("license.view")
def get_license_status():
    """Return license status, resource usage, and the per-key table."""
    context = _license_context()
    payload = context.status_payload() if context is not None else {}
    payload["required"] = bool(current_app.config.get("LICENSE_REQUIRED", False))
    payload["degraded"] = bool(current_app.config.get("LICENSE_DEGRADED", False))
    return jsonify(payload), 200


@admin_license_bp.route("/keys", methods=["POST"])
@require_auth
@require_permission("license.manage")
def add_license_key():
    """Add a key by offline envelope or by redeeming a dashboard code."""
    context = _license_context()
    data = request.get_json(silent=True) or {}
    envelope = data.get("envelope")
    code = data.get("code")

    if not envelope and code:
        envelope, error_response = _redeem_code(code)
        if error_response is not None:
            return error_response

    if not envelope:
        return (
            jsonify({"error": "Provide either an 'envelope' or a 'code'."}),
            _HTTP_BAD_REQUEST,
        )

    try:
        key, status = context.add_key(envelope)
    except LicenseKeyRejected as rejected:
        return jsonify({"error": "Key rejected", "status": rejected.status.value}), (
            _HTTP_UNPROCESSABLE
        )
    except LicenseNotConfigured as unconfigured:
        return jsonify({"error": str(unconfigured)}), _HTTP_CONFLICT

    return (
        jsonify(
            {
                "key_id": key.key_id,
                "scope": list(key.scope),
                "status": status.value,
            }
        ),
        _HTTP_CREATED,
    )


@admin_license_bp.route("/keys/<key_id>", methods=["DELETE"])
@require_auth
@require_permission("license.manage")
def remove_license_key(key_id):
    """Remove a held key by id."""
    context = _license_context()
    try:
        removed = context.remove_key(key_id)
    except LicenseNotConfigured as unconfigured:
        return jsonify({"error": str(unconfigured)}), _HTTP_CONFLICT
    if not removed:
        return jsonify({"error": "Key not found"}), _HTTP_NOT_FOUND
    return jsonify({"removed": key_id}), 200


def _redeem_code(code):
    """Exchange a dashboard code for an envelope via the hub activation client.

    Returns ``(envelope, None)`` on success or ``(None, error_response)`` on any
    misconfiguration/hub failure.
    """
    client = getattr(current_app, "license_activation_client", None)
    if client is None:
        return None, (
            jsonify({"error": "Online activation is not configured."}),
            _HTTP_BAD_REQUEST,
        )
    instance_id = getattr(current_app, "license_instance_id", "")
    try:
        return client.activate(code, instance_id), None
    except LicenseActivationError as activation_error:
        return None, (
            jsonify({"error": f"Activation failed: {activation_error}"}),
            _HTTP_BAD_GATEWAY,
        )
