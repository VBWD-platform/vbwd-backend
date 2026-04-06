"""Admin token bundle management routes."""
from flask import Blueprint, jsonify, request
from decimal import Decimal
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.repositories.token_bundle_repository import TokenBundleRepository
from vbwd.extensions import db
from vbwd.models import TokenBundle

admin_token_bundles_bp = Blueprint(
    "admin_token_bundles", __name__, url_prefix="/api/v1/admin/token-bundles"
)


@admin_token_bundles_bp.route("/", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def list_token_bundles():
    """
    List all token bundles with pagination.

    Query params:
        - page: int (default 1)
        - per_page: int (default 20)
        - include_inactive: bool (default true)

    Returns:
        200: Paginated list of token bundles
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    include_inactive = request.args.get("include_inactive", "true").lower() == "true"

    # Limit per_page to reasonable values
    per_page = min(max(per_page, 1), 100)

    bundle_repo = TokenBundleRepository(db.session)
    bundles, total = bundle_repo.find_all_paginated(
        page=page,
        per_page=per_page,
        include_inactive=include_inactive,
    )

    return (
        jsonify(
            {
                "items": [bundle.to_dict() for bundle in bundles],
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
            }
        ),
        200,
    )


@admin_token_bundles_bp.route("/", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def create_token_bundle():
    """
    Create a new token bundle.

    Body:
        - name: str (required)
        - description: str (optional)
        - token_amount: int (required)
        - price: decimal (required)
        - is_active: bool (default: true)
        - sort_order: int (default: 0)

    Returns:
        201: Created token bundle
        400: Validation error
    """
    data = request.get_json() or {}

    # Validate required fields
    if not data.get("name"):
        return jsonify({"error": "Name is required"}), 400
    if "token_amount" not in data:
        return jsonify({"error": "Token amount is required"}), 400
    if "price" not in data:
        return jsonify({"error": "Price is required"}), 400

    try:
        token_amount = int(data["token_amount"])
        if token_amount <= 0:
            return jsonify({"error": "Token amount must be positive"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid token amount"}), 400

    try:
        price = Decimal(str(data["price"]))
        if price < 0:
            return jsonify({"error": "Price cannot be negative"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid price"}), 400

    try:
        bundle = TokenBundle(
            name=data["name"],
            description=data.get("description"),
            token_amount=token_amount,
            price=price,
            is_active=data.get("is_active", True),
            sort_order=data.get("sort_order", 0),
        )

        bundle_repo = TokenBundleRepository(db.session)
        saved_bundle = bundle_repo.save(bundle)

        return (
            jsonify(
                {
                    "bundle": saved_bundle.to_dict(),
                    "message": "Token bundle created successfully",
                }
            ),
            201,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@admin_token_bundles_bp.route("/<bundle_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def get_token_bundle(bundle_id):
    """
    Get token bundle details.

    Args:
        bundle_id: UUID of the token bundle

    Returns:
        200: Token bundle details
        404: Token bundle not found
    """
    bundle_repo = TokenBundleRepository(db.session)
    bundle = bundle_repo.find_by_id(bundle_id)

    if not bundle:
        return jsonify({"error": "Token bundle not found"}), 404

    return jsonify({"bundle": bundle.to_dict()}), 200


@admin_token_bundles_bp.route("/<bundle_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("settings.manage")
def update_token_bundle(bundle_id):
    """
    Update token bundle details.

    Args:
        bundle_id: UUID of the token bundle

    Body:
        - name: str (optional)
        - description: str (optional)
        - token_amount: int (optional)
        - price: decimal (optional)
        - is_active: bool (optional)
        - sort_order: int (optional)

    Returns:
        200: Updated token bundle
        404: Token bundle not found
        400: Validation error
    """
    bundle_repo = TokenBundleRepository(db.session)
    bundle = bundle_repo.find_by_id(bundle_id)

    if not bundle:
        return jsonify({"error": "Token bundle not found"}), 404

    data = request.get_json() or {}

    if "name" in data:
        if not data["name"]:
            return jsonify({"error": "Name cannot be empty"}), 400
        bundle.name = data["name"]

    if "description" in data:
        bundle.description = data["description"]

    if "token_amount" in data:
        try:
            token_amount = int(data["token_amount"])
            if token_amount <= 0:
                return jsonify({"error": "Token amount must be positive"}), 400
            bundle.token_amount = token_amount
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid token amount"}), 400

    if "price" in data:
        try:
            price = Decimal(str(data["price"]))
            if price < 0:
                return jsonify({"error": "Price cannot be negative"}), 400
            bundle.price = price
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid price"}), 400

    if "is_active" in data:
        bundle.is_active = bool(data["is_active"])

    if "sort_order" in data:
        bundle.sort_order = int(data.get("sort_order", 0))

    saved_bundle = bundle_repo.save(bundle)

    return jsonify({"bundle": saved_bundle.to_dict()}), 200


@admin_token_bundles_bp.route("/<bundle_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("settings.manage")
def delete_token_bundle(bundle_id):
    """
    Delete a token bundle.

    Args:
        bundle_id: UUID of the token bundle

    Returns:
        200: Token bundle deleted
        404: Token bundle not found
    """
    bundle_repo = TokenBundleRepository(db.session)
    bundle = bundle_repo.find_by_id(bundle_id)

    if not bundle:
        return jsonify({"error": "Token bundle not found"}), 404

    bundle_repo.delete(bundle_id)

    return jsonify({"message": "Token bundle deleted successfully"}), 200


@admin_token_bundles_bp.route("/<bundle_id>/activate", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def activate_token_bundle(bundle_id):
    """
    Activate a token bundle.

    Args:
        bundle_id: UUID of the token bundle

    Returns:
        200: Token bundle activated
        404: Token bundle not found
    """
    bundle_repo = TokenBundleRepository(db.session)
    bundle = bundle_repo.find_by_id(bundle_id)

    if not bundle:
        return jsonify({"error": "Token bundle not found"}), 404

    bundle.is_active = True
    saved_bundle = bundle_repo.save(bundle)

    return (
        jsonify(
            {"bundle": saved_bundle.to_dict(), "message": "Token bundle activated"}
        ),
        200,
    )


@admin_token_bundles_bp.route("/<bundle_id>/deactivate", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def deactivate_token_bundle(bundle_id):
    """
    Deactivate a token bundle.

    Args:
        bundle_id: UUID of the token bundle

    Returns:
        200: Token bundle deactivated
        404: Token bundle not found
    """
    bundle_repo = TokenBundleRepository(db.session)
    bundle = bundle_repo.find_by_id(bundle_id)

    if not bundle:
        return jsonify({"error": "Token bundle not found"}), 404

    bundle.is_active = False
    saved_bundle = bundle_repo.save(bundle)

    return (
        jsonify(
            {"bundle": saved_bundle.to_dict(), "message": "Token bundle deactivated"}
        ),
        200,
    )
