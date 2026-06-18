"""Configuration routes for public settings."""
from flask import Blueprint, jsonify
from vbwd.config import AVAILABLE_LANGUAGES, DEFAULT_LANGUAGE
from vbwd.extensions import db
from vbwd.repositories.currency_repository import CurrencyRepository
from vbwd.services.core_settings_store import (
    get_core_settings,
    update_core_settings,
)
from vbwd.services.currency_service import CurrencyService

config_bp = Blueprint("config", __name__, url_prefix="/api/v1/config")


def _build_currency_service() -> CurrencyService:
    """Build a request-scoped CurrencyService over the live session + settings.

    Mirrors the admin currency route's wiring so the public projection reads
    the very same S84 source (settings = active set / default; the
    ``vbwd_currency`` catalog = per-default rates).
    """
    return CurrencyService(
        currency_repo=CurrencyRepository(db.session),
        settings_reader=get_core_settings,
        settings_writer=update_core_settings,
    )


@config_bp.route("", methods=["GET"])
@config_bp.route("/", methods=["GET"])
def get_public_config():
    """
    Get public app configuration: the global operating currency + price modes.

    No authentication required - public endpoint. This is the frontend's single
    source of truth for the checkout currency (S93). Values come straight from
    the file-backed core settings store.

    S99.0b also publishes a read-only projection of the S84 currency data so the
    view-only display switcher can convert at the render boundary:
    ``base_currency`` (rates are relative to it = the default currency),
    ``active_currencies`` (the enabled set), and ``currency_rates`` (each active
    currency's ``exchange_rate`` to base). This is a pure read — no conversion is
    computed server-side, no new storage, no admin surface.

    Returns:
        200: ``{default_currency, prices_display_mode, prices_mode_in_db,
        base_currency, active_currencies, currency_rates}``
    """
    settings = get_core_settings()
    service = _build_currency_service()
    active_currencies = service.get_active_currencies()
    currency_rates = {
        currency.code: str(currency.exchange_rate) for currency in active_currencies
    }
    return (
        jsonify(
            {
                "default_currency": settings["default_currency"],
                "prices_display_mode": settings["prices_display_mode"],
                "prices_mode_in_db": settings["prices_mode_in_db"],
                # S99.0b: read-only S84 projection for the display switcher.
                # Rates are relative to the default currency, so base == default.
                "base_currency": settings["default_currency"],
                "active_currencies": [currency.code for currency in active_currencies],
                "currency_rates": currency_rates,
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
