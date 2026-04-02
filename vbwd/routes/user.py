"""User management routes."""
from flask import Blueprint, request, jsonify, g, current_app
from marshmallow import ValidationError
from uuid import UUID
from vbwd.middleware.auth import require_auth
from vbwd.schemas.user_schemas import (
    UserSchema,
    UserDetailsSchema,
    UserDetailsUpdateSchema,
    UserProfileSchema,
)
from vbwd.services.user_service import UserService
from vbwd.services.auth_service import AuthService
from vbwd.repositories.user_repository import UserRepository
from vbwd.repositories.user_details_repository import UserDetailsRepository
from vbwd.extensions import db
from vbwd.events.checkout_events import CheckoutRequestedEvent

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

    # Initialize services
    user_repo = UserRepository(db.session)
    user_details_repo = UserDetailsRepository(db.session)
    user_service = UserService(
        user_repository=user_repo, user_details_repository=user_details_repo
    )

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

    # Initialize services
    user_repo = UserRepository(db.session)
    user_details_repo = UserDetailsRepository(db.session)
    user_service = UserService(
        user_repository=user_repo, user_details_repository=user_details_repo
    )

    # Get details — return empty object if not yet created (normal for new users)
    details = user_service.get_user_details(user_id)
    if not details:
        return jsonify({
            "first_name": None,
            "last_name": None,
            "phone": None,
            "address_line1": None,
            "address_line2": None,
            "city": None,
            "state": None,
            "postal_code": None,
            "country": None,
        }), 200

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

    # Initialize services
    user_repo = UserRepository(db.session)
    user_details_repo = UserDetailsRepository(db.session)
    user_service = UserService(
        user_repository=user_repo, user_details_repository=user_details_repo
    )

    # Update details
    details = user_service.update_user_details(user_id, data)

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

    # Initialize services
    user_repo = UserRepository(db.session)
    auth_service = AuthService(user_repository=user_repo)

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


@user_bp.route("/checkout", methods=["POST"])
@require_auth
def checkout():
    """Create checkout with subscription and optional items.

    Requires: Bearer token in Authorization header

    Request body:
        {
            "plan_id": "uuid-here",
            "token_bundle_ids": ["uuid-1", "uuid-2"],  # optional
            "add_on_ids": ["uuid-1", "uuid-2"],        # optional
            "currency": "USD"                           # optional, defaults to USD
        }

    Returns:
        200: {
            "subscription": {...},
            "invoice": {...},
            "token_bundles": [...],
            "add_ons": [...],
            "message": "Checkout created. Awaiting payment."
        }
        400: If validation fails
        404: If plan/bundle/addon not found
    """
    user_id = g.user_id
    data = request.get_json() or {}

    # Validate: at least one item required
    plan_id = data.get("plan_id")
    token_bundle_ids_raw = data.get("token_bundle_ids", [])
    add_on_ids_raw = data.get("add_on_ids", [])

    if not plan_id and not token_bundle_ids_raw and not add_on_ids_raw:
        return (
            jsonify(
                {
                    "error": "At least one item required (plan_id, token_bundle_ids, or add_on_ids)"
                }
            ),
            400,
        )

    # Parse plan UUID (optional now)
    plan_uuid = None
    if plan_id:
        try:
            plan_uuid = UUID(plan_id) if isinstance(plan_id, str) else plan_id
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid plan_id format"}), 400

    # Parse optional token bundle IDs
    token_bundle_ids = []
    for bundle_id in token_bundle_ids_raw:
        try:
            token_bundle_ids.append(
                UUID(bundle_id) if isinstance(bundle_id, str) else bundle_id
            )
        except (ValueError, TypeError):
            return jsonify({"error": f"Invalid token_bundle_id: {bundle_id}"}), 400

    # Parse optional add-on IDs
    add_on_ids = []
    for addon_id in add_on_ids_raw:
        try:
            add_on_ids.append(UUID(addon_id) if isinstance(addon_id, str) else addon_id)
        except (ValueError, TypeError):
            return jsonify({"error": f"Invalid add_on_id: {addon_id}"}), 400

    # Get currency and payment method
    currency = data.get("currency", "USD")
    payment_method_code = data.get("payment_method_code")

    # Create checkout event
    event = CheckoutRequestedEvent(
        user_id=UUID(user_id) if isinstance(user_id, str) else user_id,
        plan_id=plan_uuid,
        token_bundle_ids=token_bundle_ids,
        add_on_ids=add_on_ids,
        currency=currency,
        payment_method_code=payment_method_code,
    )

    # Dispatch event
    container = current_app.container
    dispatcher = container.event_dispatcher()
    result = dispatcher.emit(event)

    if result.success:
        # Unwrap single-item list from EventResult.combine()
        data = result.data
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        return jsonify(data), 201
    else:
        # Map error types to HTTP status codes
        # Return 400 for validation errors (not found, not active, etc.)
        # Return 500 only for system errors
        status_code = 400
        if result.error_type == "no_handler":
            status_code = 500

        return jsonify({"error": result.error}), status_code


@user_bp.route("/addons", methods=["GET"])
@require_auth
def get_user_addons():
    """Get current user's add-on subscriptions with addon details.

    Requires: Bearer token in Authorization header

    Returns:
        200: {"addon_subscriptions": [...]}
    """
    user_id = g.user_id
    container = current_app.container

    addon_sub_repo = container.addon_subscription_repository()

    addon_subs = addon_sub_repo.find_by_user(
        UUID(user_id) if isinstance(user_id, str) else user_id
    )

    result = []
    for addon_sub in addon_subs:
        data = addon_sub.to_dict()
        # Addon details are eager-loaded via relationship
        if addon_sub.addon:
            data["addon"] = {
                "name": addon_sub.addon.name,
                "slug": addon_sub.addon.slug,
                "description": addon_sub.addon.description,
                "price": str(addon_sub.addon.price) if addon_sub.addon.price else None,
                "billing_period": addon_sub.addon.billing_period
                if addon_sub.addon.billing_period
                else None,
            }
        result.append(data)

    return jsonify({"addon_subscriptions": result}), 200


@user_bp.route("/addons/<addon_sub_id>", methods=["GET"])
@require_auth
def get_addon_detail(addon_sub_id):
    """Get addon subscription detail with addon and invoice info.

    Requires: Bearer token in Authorization header

    Args:
        addon_sub_id: UUID of the addon subscription

    Returns:
        200: Addon subscription with addon and invoice details
        403: Access denied (not owner)
        404: Addon subscription not found
    """
    user_id = g.user_id
    container = current_app.container

    addon_sub_repo = container.addon_subscription_repository()
    addon_sub = addon_sub_repo.find_by_id(addon_sub_id)

    if not addon_sub:
        return jsonify({"error": "Add-on subscription not found"}), 404

    if str(addon_sub.user_id) != str(user_id):
        return jsonify({"error": "Access denied"}), 403

    data = addon_sub.to_dict()

    # Add addon details
    if addon_sub.addon:
        data["addon"] = {
            "name": addon_sub.addon.name,
            "slug": addon_sub.addon.slug,
            "description": addon_sub.addon.description,
            "price": str(addon_sub.addon.price) if addon_sub.addon.price else None,
            "billing_period": addon_sub.addon.billing_period
            if addon_sub.addon.billing_period
            else None,
        }

    # Add invoice details
    if addon_sub.invoice_id:
        invoice_repo = container.invoice_repository()
        invoice = invoice_repo.find_by_id(addon_sub.invoice_id)
        if invoice:
            data["invoice"] = {
                "id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "status": invoice.status.value,
                "amount": str(invoice.amount),
                "currency": invoice.currency,
            }

    return jsonify({"addon_subscription": data}), 200


@user_bp.route("/addons/<addon_sub_id>/cancel", methods=["POST"])
@require_auth
def cancel_addon(addon_sub_id):
    """Cancel an addon subscription.

    Requires: Bearer token in Authorization header

    Args:
        addon_sub_id: UUID of the addon subscription

    Returns:
        200: Updated addon subscription
        400: Cannot cancel (already cancelled/expired)
        403: Access denied (not owner)
        404: Addon subscription not found
    """
    from vbwd.models.enums import SubscriptionStatus

    user_id = g.user_id
    container = current_app.container

    addon_sub_repo = container.addon_subscription_repository()
    addon_sub = addon_sub_repo.find_by_id(addon_sub_id)

    if not addon_sub:
        return jsonify({"error": "Add-on subscription not found"}), 404

    if str(addon_sub.user_id) != str(user_id):
        return jsonify({"error": "Access denied"}), 403

    if addon_sub.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING):
        return jsonify({"error": "Add-on subscription cannot be cancelled"}), 400

    addon_sub.cancel()
    db.session.commit()

    return (
        jsonify(
            {
                "addon_subscription": addon_sub.to_dict(),
                "message": "Add-on cancelled successfully",
            }
        ),
        200,
    )


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
        currency=invoice.currency or "USD",
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
