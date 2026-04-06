"""Admin payment methods management routes."""
from flask import Blueprint, jsonify, request
from decimal import Decimal
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.repositories.payment_method_repository import (
    PaymentMethodRepository,
    PaymentMethodTranslationRepository,
)
from vbwd.extensions import db
from vbwd.models import PaymentMethod

admin_payment_methods_bp = Blueprint(
    "admin_payment_methods", __name__, url_prefix="/api/v1/admin/payment-methods"
)


@admin_payment_methods_bp.route("/", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.manage")
def list_payment_methods():
    """
    List all payment methods including inactive ones.

    Returns:
        200: List of all payment methods
    """
    repo = PaymentMethodRepository(db.session)
    methods = repo.find_all_ordered()

    return jsonify({"payment_methods": [m.to_dict() for m in methods]}), 200


@admin_payment_methods_bp.route("/", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def create_payment_method():
    """
    Create a new payment method.

    Body:
        - code: str (required, immutable)
        - name: str (required)
        - description: str (optional)
        - short_description: str (optional)
        - icon: str (optional)
        - plugin_id: str (optional)
        - is_active: bool (default: true)
        - is_default: bool (default: false)
        - position: int (default: 0)
        - min_amount: decimal (optional)
        - max_amount: decimal (optional)
        - currencies: list (optional)
        - countries: list (optional)
        - fee_type: str (default: 'none')
        - fee_amount: decimal (optional)
        - fee_charged_to: str (default: 'customer')
        - instructions: str (optional)
        - config: dict (optional)

    Returns:
        201: Created payment method
        400: Validation error
    """
    data = request.get_json() or {}
    repo = PaymentMethodRepository(db.session)

    # Validate required fields
    if not data.get("code"):
        return jsonify({"error": "Code is required"}), 400
    if not data.get("name"):
        return jsonify({"error": "Name is required"}), 400

    # Check for duplicate code
    if repo.code_exists(data["code"]):
        return jsonify({"error": "Code already exists"}), 400

    try:
        method = PaymentMethod(
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            short_description=data.get("short_description"),
            icon=data.get("icon"),
            plugin_id=data.get("plugin_id"),
            is_active=data.get("is_active", True),
            is_default=data.get("is_default", False),
            position=data.get("position", 0),
            min_amount=(
                Decimal(str(data["min_amount"])) if data.get("min_amount") else None
            ),
            max_amount=(
                Decimal(str(data["max_amount"])) if data.get("max_amount") else None
            ),
            currencies=data.get("currencies", []),
            countries=data.get("countries", []),
            fee_type=data.get("fee_type", "none"),
            fee_amount=(
                Decimal(str(data["fee_amount"])) if data.get("fee_amount") else None
            ),
            fee_charged_to=data.get("fee_charged_to", "customer"),
            instructions=data.get("instructions"),
            config=data.get("config", {}),
        )

        # If setting as default, clear other defaults
        if method.is_default:
            db.session.query(PaymentMethod).filter(
                PaymentMethod.is_default.is_(True)
            ).update({"is_default": False})

        saved = repo.save(method)

        return (
            jsonify(
                {
                    "payment_method": saved.to_dict(),
                    "message": "Payment method created successfully",
                }
            ),
            201,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@admin_payment_methods_bp.route("/<method_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.manage")
def get_payment_method(method_id):
    """
    Get payment method details.

    Args:
        method_id: UUID of the payment method

    Returns:
        200: Payment method details
        404: Not found
    """
    repo = PaymentMethodRepository(db.session)
    method = repo.find_by_id(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    return jsonify({"payment_method": method.to_dict()}), 200


@admin_payment_methods_bp.route("/code/<code>", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.manage")
def get_payment_method_by_code(code):
    """
    Get payment method by code.

    Args:
        code: The unique code

    Returns:
        200: Payment method details
        404: Not found
    """
    repo = PaymentMethodRepository(db.session)
    method = repo.find_by_code(code)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    return jsonify({"payment_method": method.to_dict()}), 200


@admin_payment_methods_bp.route("/<method_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("settings.manage")
def update_payment_method(method_id):
    """
    Update payment method.

    Note: code is immutable and cannot be changed.

    Args:
        method_id: UUID of the payment method

    Returns:
        200: Updated payment method
        400: Validation error
        404: Not found
    """
    repo = PaymentMethodRepository(db.session)
    method = repo.find_by_id(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    data = request.get_json() or {}

    # Code is immutable
    if "code" in data and data["code"] != method.code:
        return jsonify({"error": "Code is immutable and cannot be changed"}), 400

    # Update allowed fields
    if "name" in data:
        method.name = data["name"]
    if "description" in data:
        method.description = data["description"]
    if "short_description" in data:
        method.short_description = data["short_description"]
    if "icon" in data:
        method.icon = data["icon"]
    if "plugin_id" in data:
        method.plugin_id = data["plugin_id"]
    if "is_active" in data:
        method.is_active = data["is_active"]
    if "position" in data:
        method.position = data["position"]
    if "min_amount" in data:
        method.min_amount = (
            Decimal(str(data["min_amount"])) if data["min_amount"] else None
        )
    if "max_amount" in data:
        method.max_amount = (
            Decimal(str(data["max_amount"])) if data["max_amount"] else None
        )
    if "currencies" in data:
        method.currencies = data["currencies"]
    if "countries" in data:
        method.countries = data["countries"]
    if "fee_type" in data:
        method.fee_type = data["fee_type"]
    if "fee_amount" in data:
        method.fee_amount = (
            Decimal(str(data["fee_amount"])) if data["fee_amount"] else None
        )
    if "fee_charged_to" in data:
        method.fee_charged_to = data["fee_charged_to"]
    if "instructions" in data:
        method.instructions = data["instructions"]
    if "config" in data:
        method.config = data["config"]

    saved = repo.save(method)

    return jsonify({"payment_method": saved.to_dict()}), 200


@admin_payment_methods_bp.route("/<method_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("settings.manage")
def delete_payment_method(method_id):
    """
    Delete a payment method.

    Note: Cannot delete the default payment method.

    Args:
        method_id: UUID of the payment method

    Returns:
        200: Success
        400: Cannot delete default
        404: Not found
    """
    repo = PaymentMethodRepository(db.session)
    method = repo.find_by_id(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    if method.is_default:
        return jsonify({"error": "Cannot delete the default payment method"}), 400

    repo.delete(method_id)

    return jsonify({"message": "Payment method deleted successfully"}), 200


@admin_payment_methods_bp.route("/<method_id>/activate", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def activate_payment_method(method_id):
    """
    Activate a payment method.

    Args:
        method_id: UUID of the payment method

    Returns:
        200: Activated payment method
        404: Not found
    """
    repo = PaymentMethodRepository(db.session)
    method = repo.find_by_id(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    method.is_active = True
    saved = repo.save(method)

    return jsonify({"payment_method": saved.to_dict(), "message": "Activated"}), 200


@admin_payment_methods_bp.route("/<method_id>/deactivate", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def deactivate_payment_method(method_id):
    """
    Deactivate a payment method.

    Note: Cannot deactivate the default payment method.

    Args:
        method_id: UUID of the payment method

    Returns:
        200: Deactivated payment method
        400: Cannot deactivate default
        404: Not found
    """
    repo = PaymentMethodRepository(db.session)
    method = repo.find_by_id(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    if method.is_default:
        return jsonify({"error": "Cannot deactivate the default payment method"}), 400

    method.is_active = False
    saved = repo.save(method)

    return jsonify({"payment_method": saved.to_dict(), "message": "Deactivated"}), 200


@admin_payment_methods_bp.route("/<method_id>/set-default", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def set_default_payment_method(method_id):
    """
    Set a payment method as the default.

    Args:
        method_id: UUID of the payment method

    Returns:
        200: Updated payment method
        404: Not found
    """
    repo = PaymentMethodRepository(db.session)
    method = repo.set_default(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    return (
        jsonify({"payment_method": method.to_dict(), "message": "Set as default"}),
        200,
    )


@admin_payment_methods_bp.route("/reorder", methods=["PUT"])
@require_auth
@require_admin
@require_permission("settings.manage")
def reorder_payment_methods():
    """
    Reorder payment methods by position.

    Body:
        - order: list of {id, position}

    Returns:
        200: Updated payment methods
    """
    data = request.get_json() or {}
    order = data.get("order", [])

    if not order:
        return jsonify({"error": "Order list is required"}), 400

    repo = PaymentMethodRepository(db.session)
    updated = repo.update_positions(order)

    return jsonify({"payment_methods": [m.to_dict() for m in updated]}), 200


@admin_payment_methods_bp.route("/<method_id>/translations", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.manage")
def get_translations(method_id):
    """
    Get all translations for a payment method.

    Args:
        method_id: UUID of the payment method

    Returns:
        200: List of translations
        404: Payment method not found
    """
    method_repo = PaymentMethodRepository(db.session)
    method = method_repo.find_by_id(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    trans_repo = PaymentMethodTranslationRepository(db.session)
    translations = trans_repo.find_by_method(method_id)

    return jsonify({"translations": [t.to_dict() for t in translations]}), 200


@admin_payment_methods_bp.route("/<method_id>/translations", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.manage")
def add_translation(method_id):
    """
    Add or update a translation for a payment method.

    Body:
        - locale: str (required)
        - name: str (optional)
        - description: str (optional)
        - short_description: str (optional)
        - instructions: str (optional)

    Returns:
        200/201: Translation
        400: Validation error
        404: Payment method not found
    """
    method_repo = PaymentMethodRepository(db.session)
    method = method_repo.find_by_id(method_id)

    if not method:
        return jsonify({"error": "Payment method not found"}), 404

    data = request.get_json() or {}

    if not data.get("locale"):
        return jsonify({"error": "Locale is required"}), 400

    trans_repo = PaymentMethodTranslationRepository(db.session)
    translation = trans_repo.upsert(
        payment_method_id=method_id,
        locale=data["locale"],
        name=data.get("name"),
        description=data.get("description"),
        short_description=data.get("short_description"),
        instructions=data.get("instructions"),
    )

    return jsonify({"translation": translation.to_dict()}), 200
