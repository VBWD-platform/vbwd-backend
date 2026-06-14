"""Configuration routes for public settings."""
from flask import Blueprint, jsonify
from vbwd.config import AVAILABLE_LANGUAGES, DEFAULT_LANGUAGE
from vbwd.services.core_settings_store import get_core_settings

config_bp = Blueprint("config", __name__, url_prefix="/api/v1/config")


@config_bp.route("", methods=["GET"])
@config_bp.route("/", methods=["GET"])
def get_public_config():
    """
    Get public app configuration: the global operating currency + price modes.

    No authentication required - public endpoint. This is the frontend's single
    source of truth for the checkout currency (S93). Values come straight from
    the file-backed core settings store.

    Returns:
        200: ``{default_currency, prices_display_mode, prices_mode_in_db}``
    """
    settings = get_core_settings()
    return (
        jsonify(
            {
                "default_currency": settings["default_currency"],
                "prices_display_mode": settings["prices_display_mode"],
                "prices_mode_in_db": settings["prices_mode_in_db"],
            }
        ),
        200,
    )


@config_bp.route("/languages", methods=["GET"])
def get_languages():
    """
    Get available languages and default language.

    No authentication required - public endpoint.

    Returns:
        200: List of available languages and default
    """
    return jsonify({"languages": AVAILABLE_LANGUAGES, "default": DEFAULT_LANGUAGE}), 200
