"""Admin settings routes."""
from flask import Blueprint, jsonify, request
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.services.core_settings_store import (
    get_core_settings,
    update_core_settings,
)

admin_settings_bp = Blueprint("admin_settings", __name__, url_prefix="/api/v1/admin")


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
    return jsonify({"settings": get_core_settings()}), 200


@admin_settings_bp.route("/settings", methods=["PUT"])
@require_auth
@require_admin
@require_permission("settings.manage")
def update_settings():
    """
    Update admin settings.

    Body:
        Any settings key-value pairs (unknown keys are ignored)

    Returns:
        200: Updated settings
    """
    data = request.get_json() or {}
    return (
        jsonify(
            {
                "settings": update_core_settings(data),
                "message": "Settings updated successfully",
            }
        ),
        200,
    )
