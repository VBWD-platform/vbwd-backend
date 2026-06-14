"""Admin currency routes (S84).

The active set + default currency live in the core settings JSON (the single
source of truth); ``vbwd_currency`` is the catalog + rates only. ``GET``
composes the catalog with ``is_active``/``is_default`` DERIVED from settings;
activate/deactivate/set-default write settings; the rate ``PUT`` writes the
table. All work flows through ``CurrencyService`` so settings stays the one
source of truth.
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.repositories.currency_repository import CurrencyRepository
from vbwd.services.core_settings_store import (
    get_core_settings,
    update_core_settings,
)
from vbwd.services.currency_service import CurrencyService

admin_currencies_bp = Blueprint(
    "admin_currencies", __name__, url_prefix="/api/v1/admin/currencies"
)


def _build_service() -> CurrencyService:
    """Build a request-scoped CurrencyService over the live session + settings."""
    return CurrencyService(
        currency_repo=CurrencyRepository(db.session),
        settings_reader=get_core_settings,
        settings_writer=update_core_settings,
    )


@admin_currencies_bp.route("", methods=["GET"])
@require_auth
@require_permission("settings.view")
def list_currencies():
    """List the catalog with is_active/is_default derived from settings."""
    service = _build_service()
    return jsonify({"currencies": service.get_catalog_view()}), 200


@admin_currencies_bp.route("", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def create_currency():
    """Add a new catalog currency (inactive by default)."""
    data = request.get_json() or {}
    code = data.get("code")
    name = data.get("name")
    symbol = data.get("symbol")
    if not code or not name or not symbol:
        return jsonify({"error": "code, name and symbol are required"}), 400

    raw_rate = data.get("exchange_rate", "1.0")
    try:
        exchange_rate = str(Decimal(str(raw_rate)))
    except (InvalidOperation, ValueError):
        return jsonify({"error": "exchange_rate must be a number"}), 400

    decimal_places = data.get("decimal_places", 2)
    if not isinstance(decimal_places, int) or isinstance(decimal_places, bool):
        return jsonify({"error": "decimal_places must be an integer"}), 400

    service = _build_service()
    try:
        currency = service.create_currency(
            code=code,
            name=name,
            symbol=symbol,
            decimal_places=decimal_places,
            exchange_rate=exchange_rate,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    db.session.commit()
    return jsonify({"currency": currency.to_dict()}), 201


@admin_currencies_bp.route("/<code>", methods=["DELETE"])
@require_auth
@require_permission("settings.manage")
def delete_currency(code):
    """Delete a catalog currency (only inactive, non-default rows)."""
    service = _build_service()
    try:
        service.delete_currency(code)
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    db.session.commit()
    return jsonify({"currencies": service.get_catalog_view()}), 200


@admin_currencies_bp.route("/<code>/activate", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def activate_currency(code):
    """Add a currency to the active set."""
    service = _build_service()
    try:
        service.set_active(code, True)
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    db.session.commit()
    return jsonify({"currencies": service.get_catalog_view()}), 200


@admin_currencies_bp.route("/<code>/deactivate", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def deactivate_currency(code):
    """Remove a currency from the active set (the default cannot be removed)."""
    service = _build_service()
    if not service.get_currency_by_code(code):
        return jsonify({"error": f"Currency not found: {code}"}), 404
    try:
        service.set_active(code, False)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    db.session.commit()
    return jsonify({"currencies": service.get_catalog_view()}), 200


@admin_currencies_bp.route("/<code>/set-default", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def set_default_currency(code):
    """Make a currency the default and re-base the catalog rates."""
    service = _build_service()
    if not service.get_currency_by_code(code):
        return jsonify({"error": f"Currency not found: {code}"}), 404
    try:
        service.set_default(code)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    db.session.commit()
    return jsonify({"currencies": service.get_catalog_view()}), 200


@admin_currencies_bp.route("/<code>/rate", methods=["PUT"])
@require_auth
@require_permission("settings.manage")
def update_currency_rate(code):
    """Update a currency's exchange rate (the default's rate is fixed at 1.0)."""
    service = _build_service()
    if not service.get_currency_by_code(code):
        return jsonify({"error": f"Currency not found: {code}"}), 404

    data = request.get_json() or {}
    raw_rate = data.get("exchange_rate")
    if raw_rate is None:
        return jsonify({"error": "exchange_rate is required"}), 400
    try:
        rate = Decimal(str(raw_rate))
    except (InvalidOperation, ValueError):
        return jsonify({"error": "exchange_rate must be a number"}), 400

    try:
        currency = service.update_exchange_rate(code, rate)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    db.session.commit()
    return jsonify({"currency": currency.to_dict()}), 200
