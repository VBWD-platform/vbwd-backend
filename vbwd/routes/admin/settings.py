"""Admin settings routes."""
from flask import Blueprint, jsonify, request
from vbwd.middleware.auth import require_auth, require_admin, require_permission

admin_settings_bp = Blueprint("admin_settings", __name__, url_prefix="/api/v1/admin")

# In-memory settings store (in production, use database or config service)
_settings = {
    "provider_name": "",
    "contact_email": "",
    "website_url": "",
    "other_links": "",
    "address_street": "",
    "address_city": "",
    "address_postal_code": "",
    "address_country": "",
    "bank_name": "",
    "bank_iban": "",
    "bank_bic": "",
}


@admin_settings_bp.route("/settings", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def get_settings():
    """
    Get admin settings.

    Returns:
        200: Settings object
    """
    return jsonify({"settings": _settings}), 200


@admin_settings_bp.route("/settings", methods=["PUT"])
@require_auth
@require_admin
@require_permission("settings.manage")
def update_settings():
    """
    Update admin settings.

    Body:
        Any settings key-value pairs

    Returns:
        200: Updated settings
    """
    data = request.get_json() or {}

    # Update only known keys
    for key in _settings:
        if key in data:
            _settings[key] = data[key]

    return (
        jsonify({"settings": _settings, "message": "Settings updated successfully"}),
        200,
    )
