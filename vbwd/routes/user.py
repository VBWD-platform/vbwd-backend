"""User management routes."""
from flask import Blueprint, request, jsonify, g, current_app
from marshmallow import ValidationError
from uuid import UUID
from vbwd.middleware.auth import require_auth
from vbwd.services.core_settings_store import get_default_currency
from vbwd.schemas.user_schemas import (
    UserSchema,
    UserDetailsSchema,
    UserDetailsUpdateSchema,
    UserProfileSchema,
)

# Create blueprint
user_bp = Blueprint("user", __name__, url_prefix="/api/v1/user")

# Initialize schemas
user_schema = UserSchema()
user_details_schema = UserDetailsSchema()
user_details_update_schema = UserDetailsUpdateSchema()
user_profile_schema = UserProfileSchema()


@user_bp.route("/profile", methods=["GET"])
@require_auth
def get_profile():
    """Get current user's profile (user + details).

    Requires: Bearer token in Authorization header

    Returns:
        200: {
            "user": {
                "id": "uuid-here",
                "email": "user@example.com",
                "status": "ACTIVE",
                "role": "user",
                ...
            },
            "details": {
                "id": "uuid-here",
                "user_id": "uuid-here",
                "first_name": "John",
                "last_name": "Doe",
                ...
            }
        }
        404: If user not found
    """
    user_id = g.user_id

    # S08 — pull service from container.
    user_service = current_app.container.user_service()

    # Get user and details
    user = user_service.get_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    details = user_service.get_user_details(user_id)

    # Return profile
    return jsonify(user_profile_schema.dump({"user": user, "details": details})), 200


@user_bp.route("/details", methods=["GET"])
@require_auth
def get_details():
    """Get current user's details.

    Requires: Bearer token in Authorization header

    Returns:
        200: UserDetails object
        404: If details not found
    """
    user_id = g.user_id

    # S08 — pull service from container.
    user_service = current_app.container.user_service()

    # Get details — return empty object if not yet created (normal for new users)
    details = user_service.get_user_details(user_id)
    if not details:
        return (
            jsonify(
                {
                    "first_name": None,
                    "last_name": None,
                    "phone": None,
                    "address_line1": None,
                    "address_line2": None,
                    "city": None,
                    "state": None,
                    "postal_code": None,
                    "country": None,
                }
            ),
            200,
        )

    return jsonify(user_details_schema.dump(details)), 200


@user_bp.route("/details", methods=["PUT"])
@require_auth
def update_details():
    """Update current user's details.

    Requires: Bearer token in Authorization header

    Request body:
        {
            "first_name": "John",
            "last_name": "Doe",
            "phone": "+1234567890",
            "address_line_1": "123 Main St",
            "address_line_2": "Apt 4B",
            "city": "New York",
            "postal_code": "10001",
            "country": "US"
        }

    Returns:
        200: Updated UserDetails object
        400: If validation fails
    """
    user_id = g.user_id

    try:
        # Validate request data
        data = user_details_update_schema.load(request.json)
    except ValidationError as err:
        return jsonify({"error": err.messages}), 400

    # S08 — pull service from container.
    user_service = current_app.container.user_service()

    # Update details (S74 — business account requires a company name).
    from vbwd.models.user_details import AccountTypeValidationError

    try:
        details = user_service.update_user_details(user_id, data)
    except AccountTypeValidationError as account_error:
        return jsonify({"error": str(account_error)}), 400

    return jsonify(user_details_schema.dump(details)), 200


@user_bp.route("/change-password", methods=["POST"])
@require_auth
def change_password():
    """Change current user's password.

    Requires: Bearer token in Authorization header

    Request body:
        {
            "currentPassword": "OldPassword123!",
            "newPassword": "NewPassword123!"
        }

    Returns:
        200: {"success": true}
        400: If validation fails or current password is wrong
    """
    user_id = g.user_id
    data = request.get_json() or {}

    current_password = data.get("currentPassword")
    new_password = data.get("newPassword")

    if not current_password or not new_password:
        return jsonify({"error": "Current password and new password are required"}), 400

    # S08 — pull from container.
    user_repo = current_app.container.user_repository()
    auth_service = current_app.container.auth_service()

    # Get user
    user = user_repo.find_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Verify current password
    if not auth_service.verify_password(current_password, user.password_hash):
        return jsonify({"error": "Current password is incorrect"}), 400

    # Update password
    user.password_hash = auth_service.hash_password(new_password)
    user_repo.save(user)

    return jsonify({"success": True}), 200


@user_bp.route("/tokens/balance", methods=["GET"])
@require_auth
def get_token_balance():
    """
    Get current user's token balance.

    Requires: Bearer token in Authorization header

    Returns:
        200: {"balance": 1000, "transactions": [...]}
    """
    user_id = g.user_id
    container = current_app.container

    # Get balance
    balance_repo = container.token_balance_repository()
    balance = balance_repo.find_by_user_id(
        UUID(user_id) if isinstance(user_id, str) else user_id
    )

    return (
        jsonify(
            {
                "balance": balance.balance if balance else 0,
            }
        ),
        200,
    )


@user_bp.route("/tokens/transactions", methods=["GET"])
@require_auth
def get_token_transactions():
    """
    Get current user's token transaction history.

    Requires: Bearer token in Authorization header

    Query params:
        - limit: int (default 50)
        - offset: int (default 0)

    Returns:
        200: {"transactions": [...], "total": 10}
    """
    user_id = g.user_id
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    container = current_app.container
    transaction_repo = container.token_transaction_repository()

    transactions = transaction_repo.find_by_user_id(
        UUID(user_id) if isinstance(user_id, str) else user_id,
        limit=limit,
        offset=offset,
    )

    return (
        jsonify(
            {
                "transactions": [t.to_dict() for t in transactions],
            }
        ),
        200,
    )


@user_bp.route("/invoices/<invoice_id>/pay", methods=["POST"])
@require_auth
def pay_invoice(invoice_id):
    """
    Pay an invoice for the current user.

    This endpoint simulates payment processing. In production, this would
    redirect to or integrate with an external payment provider.

    Requires: Bearer token in Authorization header

    Returns:
        200: {"invoice": {...}, "message": "Payment successful"}
        400: {"error": "Invoice already paid"}
        403: {"error": "Access denied"}
        404: {"error": "Invoice not found"}
    """
    from vbwd.events.payment_events import PaymentCapturedEvent

    user_id = g.user_id

    container = current_app.container
    invoice_service = container.invoice_service()

    # Get the invoice and verify ownership
    invoice = invoice_service.get_by_id(invoice_id)
    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    # Verify the invoice belongs to the current user
    if str(invoice.user_id) != str(user_id):
        return jsonify({"error": "Access denied"}), 403

    # Check if already paid
    if invoice.status.value == "PAID":
        return jsonify({"error": "Invoice already paid"}), 400

    # Dispatch payment event to trigger full payment flow
    # (marks invoice paid, activates subscription, credits tokens, etc.)
    event = PaymentCapturedEvent(
        invoice_id=UUID(invoice_id) if isinstance(invoice_id, str) else invoice_id,
        payment_reference=f"user-payment-{invoice_id[:8]}",
        amount=str(invoice.amount),
        currency=invoice.currency or get_default_currency(),
    )

    dispatcher = container.event_dispatcher()
    result = dispatcher.emit(event)

    if not result.success:
        return jsonify({"error": result.error or "Payment failed"}), 400

    # Get updated invoice
    updated_invoice = invoice_service.get_by_id(invoice_id)

    return (
        jsonify(
            {
                "invoice": updated_invoice.to_dict() if updated_invoice else {},
                "message": "Payment successful",
            }
        ),
        200,
    )
