"""Admin tax configuration routes — CRUD for tax rates."""
from uuid import uuid4

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.models.tax import Tax

admin_tax_bp = Blueprint("admin_tax", __name__, url_prefix="/api/v1/admin/tax")


# ── Tax Rates ──────────────────────────────────────────────────────────


@admin_tax_bp.route("/rates", methods=["GET"])
@require_auth
@require_permission("settings.manage")
def list_rates():
    """List tax rates with optional filters."""
    country = request.args.get("country")
    is_active = request.args.get("is_active")
    tax_class = request.args.get("tax_class")

    query = db.session.query(Tax)

    if country:
        query = query.filter_by(country_code=country.upper())
    if is_active is not None:
        query = query.filter_by(is_active=is_active.lower() == "true")
    if tax_class:
        query = query.filter_by(tax_class=tax_class)

    taxes = query.order_by(Tax.country_code, Tax.code).all()
    return jsonify({"rates": [tax.to_dict() for tax in taxes]}), 200


@admin_tax_bp.route("/rates", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def create_rate():
    """Create a new tax rate."""
    data = request.get_json() or {}

    name = data.get("name", "").strip()
    code = data.get("code", "").strip().upper()
    if not name or not code:
        return jsonify({"error": "name and code are required"}), 400

    rate_value = data.get("rate")
    if rate_value is None:
        return jsonify({"error": "rate is required"}), 400

    if db.session.query(Tax).filter_by(code=code).first():
        return jsonify({"error": f"Tax code '{code}' already exists"}), 400

    tax = Tax(
        id=uuid4(),
        name=name,
        code=code,
        description=data.get("description", ""),
        rate=rate_value,
        country_code=data.get("country_code", "").upper() or None,
        region_code=data.get("region_code", "").strip() or None,
        tax_class=data.get("tax_class") or None,
        is_active=data.get("is_active", True),
        is_inclusive=data.get("is_inclusive", False),
    )

    db.session.add(tax)
    db.session.commit()
    return jsonify({"rate": tax.to_dict()}), 201


@admin_tax_bp.route("/rates/<rate_id>", methods=["GET"])
@require_auth
@require_permission("settings.manage")
def get_rate(rate_id):
    """Get a single tax rate by ID."""
    tax = db.session.query(Tax).filter_by(id=rate_id).first()
    if not tax:
        return jsonify({"error": "Tax rate not found"}), 404
    return jsonify({"rate": tax.to_dict()}), 200


@admin_tax_bp.route("/rates/<rate_id>", methods=["PUT"])
@require_auth
@require_permission("settings.manage")
def update_rate(rate_id):
    """Update an existing tax rate."""
    tax = db.session.query(Tax).filter_by(id=rate_id).first()
    if not tax:
        return jsonify({"error": "Tax rate not found"}), 404

    data = request.get_json() or {}

    if "name" in data:
        tax.name = data["name"].strip()
    if "code" in data:
        new_code = data["code"].strip().upper()
        existing = db.session.query(Tax).filter_by(code=new_code).first()
        if existing and str(existing.id) != str(tax.id):
            return (
                jsonify({"error": f"Tax code '{new_code}' already exists"}),
                400,
            )
        tax.code = new_code
    if "description" in data:
        tax.description = data["description"]
    if "rate" in data:
        tax.rate = data["rate"]
    if "country_code" in data:
        tax.country_code = (
            data["country_code"].upper() if data["country_code"] else None
        )
    if "region_code" in data:
        tax.region_code = data["region_code"] or None
    if "tax_class" in data:
        tax.tax_class = data["tax_class"] or None
    if "is_active" in data:
        tax.is_active = data["is_active"]
    if "is_inclusive" in data:
        tax.is_inclusive = data["is_inclusive"]

    db.session.commit()
    return jsonify({"rate": tax.to_dict()}), 200


@admin_tax_bp.route("/rates/<rate_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.manage")
def delete_rate(rate_id):
    """Delete a tax rate."""
    tax = db.session.query(Tax).filter_by(id=rate_id).first()
    if not tax:
        return jsonify({"error": "Tax rate not found"}), 404

    db.session.delete(tax)
    try:
        db.session.commit()
    except IntegrityError:
        # The tax is referenced by an entity (e.g. a plugin's
        # *_tax join table, ON DELETE RESTRICT). Report a clean 409
        # instead of letting the FK violation surface as a 500.
        db.session.rollback()
        return (
            jsonify({"error": "Tax rate is in use and cannot be deleted"}),
            409,
        )
    return jsonify({"message": "Tax rate deleted"}), 200
