"""Admin tariff plan category management routes."""
from flask import Blueprint, jsonify, request
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.repositories.tarif_plan_category_repository import TarifPlanCategoryRepository
from vbwd.repositories.tarif_plan_repository import TarifPlanRepository
from vbwd.services.tarif_plan_category_service import TarifPlanCategoryService
from vbwd.extensions import db

admin_categories_bp = Blueprint(
    "admin_categories",
    __name__,
    url_prefix="/api/v1/admin/tarif-plan-categories",
)


def _get_service() -> TarifPlanCategoryService:
    """Get category service with current request session."""
    return TarifPlanCategoryService(
        category_repo=TarifPlanCategoryRepository(db.session),
        tarif_plan_repo=TarifPlanRepository(db.session),
    )


@admin_categories_bp.route("/", methods=["GET"])
@require_auth
@require_admin
@require_permission("subscription.plans.manage")
def list_categories():
    """
    List tariff plan categories.

    Query params:
        format: "tree" for nested hierarchy, default flat list

    Returns:
        200: List of categories
    """
    service = _get_service()
    fmt = request.args.get("format", "flat")

    if fmt == "tree":
        categories = service.get_tree()
    else:
        categories = service.get_all()

    return jsonify({"categories": [c.to_dict() for c in categories]}), 200


@admin_categories_bp.route("/", methods=["POST"])
@require_auth
@require_admin
@require_permission("subscription.plans.manage")
def create_category():
    """
    Create a new tariff plan category.

    Body:
        name: str (required)
        slug: str (optional, auto-generated)
        description: str (optional)
        parent_id: UUID (optional)
        is_single: bool (default: true)
        sort_order: int (default: 0)

    Returns:
        201: Created category
        400: Validation error
    """
    data = request.get_json() or {}

    if not data.get("name"):
        return jsonify({"error": "Name is required"}), 400

    try:
        service = _get_service()
        category = service.create(
            name=data["name"],
            slug=data.get("slug"),
            description=data.get("description"),
            parent_id=data.get("parent_id"),
            is_single=data.get("is_single", True),
            sort_order=int(data.get("sort_order", 0)),
        )
        return (
            jsonify(
                {
                    "category": category.to_dict(),
                    "message": "Category created successfully",
                }
            ),
            201,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@admin_categories_bp.route("/<category_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("subscription.plans.manage")
def get_category(category_id):
    """
    Get category detail.

    Returns:
        200: Category details
        404: Not found
    """
    service = _get_service()
    category = service.get_by_id(category_id)

    if not category:
        return jsonify({"error": "Category not found"}), 404

    return jsonify({"category": category.to_dict()}), 200


@admin_categories_bp.route("/<category_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("subscription.plans.manage")
def update_category(category_id):
    """
    Update tariff plan category.

    Returns:
        200: Updated category
        400: Validation error
        404: Not found
    """
    data = request.get_json() or {}

    try:
        service = _get_service()
        category = service.update(category_id, **data)
        return jsonify({"category": category.to_dict()}), 200
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            return jsonify({"error": msg}), 404
        return jsonify({"error": msg}), 400


@admin_categories_bp.route("/<category_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("subscription.plans.manage")
def delete_category(category_id):
    """
    Delete a tariff plan category.

    Returns:
        200: Deleted
        400: Cannot delete (root or has children)
        404: Not found
    """
    try:
        service = _get_service()
        service.delete(category_id)
        return jsonify({"message": "Category deleted successfully"}), 200
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            return jsonify({"error": msg}), 404
        return jsonify({"error": msg}), 400


@admin_categories_bp.route("/<category_id>/attach-plans", methods=["POST"])
@require_auth
@require_admin
@require_permission("subscription.plans.manage")
def attach_plans(category_id):
    """
    Attach plans to a category.

    Body:
        plan_ids: list of UUID strings

    Returns:
        200: Updated category
        400: Validation error
    """
    data = request.get_json() or {}
    plan_ids = data.get("plan_ids", [])

    if not plan_ids:
        return jsonify({"error": "plan_ids is required"}), 400

    try:
        service = _get_service()
        category = service.attach_plans(category_id, plan_ids)
        return jsonify({"category": category.to_dict()}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@admin_categories_bp.route("/<category_id>/detach-plans", methods=["POST"])
@require_auth
@require_admin
@require_permission("subscription.plans.manage")
def detach_plans(category_id):
    """
    Detach plans from a category.

    Body:
        plan_ids: list of UUID strings

    Returns:
        200: Updated category
        400: Validation error
    """
    data = request.get_json() or {}
    plan_ids = data.get("plan_ids", [])

    if not plan_ids:
        return jsonify({"error": "plan_ids is required"}), 400

    try:
        service = _get_service()
        category = service.detach_plans(category_id, plan_ids)
        return jsonify({"category": category.to_dict()}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
