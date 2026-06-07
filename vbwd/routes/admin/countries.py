"""Admin countries configuration routes."""
from flask import Blueprint, jsonify, request
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.repositories.country_repository import CountryRepository
from vbwd.extensions import db

admin_countries_bp = Blueprint(
    "admin_countries", __name__, url_prefix="/api/v1/admin/countries"
)


@admin_countries_bp.route("/", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def list_countries():
    """
    List all countries (enabled and disabled).

    Returns:
        200: List of all countries with enabled first, then by position/name
    """
    repo = CountryRepository(db.session)
    countries = repo.find_all_ordered()

    return jsonify({"countries": [c.to_dict() for c in countries]}), 200


@admin_countries_bp.route("/<code>/enable", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def enable_country(code: str):
    """
    Enable a country for billing address selection.

    Args:
        code: ISO 3166-1 alpha-2 country code

    Returns:
        200: Updated country
        404: Country not found
    """
    repo = CountryRepository(db.session)
    country = repo.find_by_code(code)

    if not country:
        return jsonify({"error": f"Country '{code}' not found"}), 404

    if country.is_enabled:
        return jsonify(country.to_dict()), 200

    # Set position to end of enabled list
    from sqlalchemy import func

    max_pos = db.session.query(
        func.max(
            db.session.query(repo._model)
            .filter(repo._model.is_enabled.is_(True))
            .subquery()
            .c.position
        )
    ).scalar()
    if max_pos is None:
        max_pos = (
            db.session.query(func.max(repo._model.position))
            .filter(repo._model.is_enabled.is_(True))
            .scalar()
        )

    country.is_enabled = True  # type: ignore[assignment]
    country.position = (max_pos or -1) + 1  # type: ignore[assignment]

    db.session.commit()
    db.session.refresh(country)

    return jsonify(country.to_dict()), 200


@admin_countries_bp.route("/<code>/disable", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def disable_country(code: str):
    """
    Disable a country from billing address selection.

    Args:
        code: ISO 3166-1 alpha-2 country code

    Returns:
        200: Updated country
        404: Country not found
    """
    repo = CountryRepository(db.session)
    country = repo.find_by_code(code)

    if not country:
        return jsonify({"error": f"Country '{code}' not found"}), 404

    country.is_enabled = False  # type: ignore[assignment]
    country.position = 999  # type: ignore[assignment]

    db.session.commit()
    db.session.refresh(country)

    return jsonify(country.to_dict()), 200


@admin_countries_bp.route("/reorder", methods=["PUT"])
@require_auth
@require_admin
@require_permission("settings.manage")
def reorder_countries():
    """
    Reorder enabled countries.

    Body:
        - codes: list of country codes in desired order

    Returns:
        200: Updated list of enabled countries
        400: Invalid request
    """
    data = request.get_json() or {}
    codes = data.get("codes", [])

    if not codes:
        return jsonify({"error": "codes list required"}), 400

    if not isinstance(codes, list):
        return jsonify({"error": "codes must be a list"}), 400

    repo = CountryRepository(db.session)

    # Update positions based on order
    for position, code in enumerate(codes):
        country = repo.find_by_code(code)
        if country and country.is_enabled:
            country.position = position

    db.session.commit()

    # Return updated enabled countries
    enabled = repo.find_enabled()
    return jsonify({"countries": [c.to_dict() for c in enabled]}), 200


@admin_countries_bp.route("/enabled", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def list_enabled_countries():
    """
    List only enabled countries in position order.

    Returns:
        200: List of enabled countries
    """
    repo = CountryRepository(db.session)
    countries = repo.find_enabled()

    return jsonify({"countries": [c.to_dict() for c in countries]}), 200


@admin_countries_bp.route("/disabled", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def list_disabled_countries():
    """
    List only disabled countries.

    Returns:
        200: List of disabled countries
    """
    repo = CountryRepository(db.session)
    countries = repo.find_disabled()

    return jsonify({"countries": [c.to_dict() for c in countries]}), 200
