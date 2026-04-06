"""Admin user management routes."""
import bcrypt
from uuid import UUID
from flask import Blueprint, jsonify, request, current_app
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.repositories.user_repository import UserRepository
from vbwd.extensions import db
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.models.user_token_balance import UserTokenBalance
from vbwd.models.enums import UserStatus, UserRole

admin_users_bp = Blueprint("admin_users", __name__, url_prefix="/api/v1/admin/users")


@admin_users_bp.route("/", methods=["POST"])
@require_auth
@require_admin
@require_permission("users.manage")
def create_user():
    """
    Create new user with optional details.

    Body:
        - email: str (required)
        - password: str (required, min 8 chars)
        - status: str (optional, default 'active')
        - role: str (optional, default 'user')
        - details: object (optional)

    Returns:
        201: Created user
        400: Validation error
        409: Email already exists
    """
    data = request.get_json() or {}

    # Validate required fields
    if not data.get("email"):
        return jsonify({"error": "Email is required"}), 400
    if not data.get("password"):
        return jsonify({"error": "Password is required"}), 400
    if len(data.get("password", "")) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    user_repo = UserRepository(db.session)

    # Check if email already exists
    existing = user_repo.find_by_email(data["email"])
    if existing:
        return jsonify({"error": "User with this email already exists"}), 409

    # Hash password
    password_bytes = data["password"].encode("utf-8")
    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")

    # Parse status
    status_str = data.get("status", "ACTIVE")
    try:
        status = UserStatus(status_str)
    except ValueError:
        return jsonify({"error": f"Invalid status: {status_str}"}), 400

    # Parse role
    role_str = data.get("role", "USER")
    try:
        role = UserRole(role_str)
    except ValueError:
        return jsonify({"error": f"Invalid role: {role_str}"}), 400

    # Create user
    user = User()
    user.email = data["email"]
    user.password_hash = password_hash
    user.status = status
    user.role = role

    created_user = user_repo.save(user)

    # Create user details if provided
    details_data = data.get("details")
    if details_data:
        user_details = UserDetails()
        user_details.user_id = created_user.id
        user_details.first_name = details_data.get("first_name")
        user_details.last_name = details_data.get("last_name")
        user_details.address_line_1 = details_data.get("address_line_1")
        user_details.address_line_2 = details_data.get("address_line_2")
        user_details.city = details_data.get("city")
        user_details.postal_code = details_data.get("postal_code")
        user_details.country = details_data.get("country")
        user_details.phone = details_data.get("phone")
        db.session.add(user_details)
        db.session.commit()
        created_user.details = user_details

    # Dispatch user:created event
    try:
        dispatcher = current_app.container.event_dispatcher()
        dispatcher.emit(
            "user:created",
            {
                "user_id": str(created_user.id),
                "email": created_user.email,
                "role": created_user.role.value,
            },
        )
    except Exception:
        pass  # Don't fail if event dispatcher not configured

    # Build response
    response = {
        "id": str(created_user.id),
        "email": created_user.email,
        "status": created_user.status.value,
        "role": created_user.role.value,
        "created_at": created_user.created_at.isoformat()
        if created_user.created_at
        else None,
    }
    if created_user.details:
        response["details"] = created_user.details.to_dict()

    return jsonify(response), 201


@admin_users_bp.route("/", methods=["GET"])
@require_auth
@require_admin
@require_permission("users.view")
def list_users():
    """
    List all users with pagination and filters.

    Query params:
        - limit: int (default 20, max 100)
        - offset: int (default 0)
        - status: str (active, pending, suspended, deleted)
        - search: str (email search)

    Returns:
        200: List of users with pagination info
        401: Unauthorized
        403: Forbidden (non-admin)
    """
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status")
    search = request.args.get("search")

    user_repo = UserRepository(db.session)

    users, total = user_repo.find_all_paginated(
        limit=limit, offset=offset, status=status, search=search
    )

    return (
        jsonify(
            {
                "users": [user.to_dict() for user in users],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        ),
        200,
    )


@admin_users_bp.route("/<user_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("users.view")
def get_user(user_id):
    """
    Get user detail.

    Args:
        user_id: UUID of the user

    Returns:
        200: User details
        404: User not found
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": user.to_dict()}), 200


@admin_users_bp.route("/<user_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("users.manage")
def update_user(user_id):
    """
    Update user details.

    Args:
        user_id: UUID of the user

    Body:
        - status: str (optional, 'active', 'suspended', etc.)
        - is_active: bool (optional, alternative to status)
        - role: str (optional)
        - name: str (optional, full name to split into first/last)
        - password: str (optional, min 8 chars if provided)
        - balance: float (optional, user account balance)

    Returns:
        200: Updated user
        404: User not found
        400: Validation error (invalid password or balance)
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}

    # Handle is_active -> status conversion (frontend sends is_active)
    if "is_active" in data:
        user.status = UserStatus.ACTIVE if data["is_active"] else UserStatus.SUSPENDED

    # Handle legacy status field
    if "status" in data:
        try:
            user.status = UserStatus(data["status"])
        except ValueError:
            return jsonify({"error": f"Invalid status: {data['status']}"}), 400

    if "role" in data:
        try:
            user.role = UserRole(data["role"])
        except ValueError:
            return jsonify({"error": f"Invalid role: {data['role']}"}), 400

    # Handle password update (optional)
    if "password" in data and data["password"]:
        if len(data["password"]) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400
        password_bytes = data["password"].encode("utf-8")
        user.password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode(
            "utf-8"
        )

    # Collect detail field names that can be updated
    detail_fields = [
        "first_name",
        "last_name",
        "phone",
        "address_line_1",
        "address_line_2",
        "city",
        "postal_code",
        "country",
        "company",
        "tax_number",
    ]

    # Check if any detail field is provided
    has_detail_updates = any(k in data for k in detail_fields)
    has_name_update = "name" in data and data["name"]
    has_balance_update = "balance" in data

    needs_details = has_detail_updates or has_name_update or has_balance_update
    if needs_details and not user.details:
        user_details = UserDetails()
        user_details.user_id = user.id
        db.session.add(user_details)
        db.session.flush()
        db.session.refresh(user)

    # Handle individual detail fields
    if has_detail_updates and user.details:
        for field in detail_fields:
            if field in data:
                setattr(user.details, field, data[field] or None)

    # Handle name -> UserDetails (legacy: frontend sends combined name)
    if has_name_update and not has_detail_updates:
        parts = data["name"].strip().split(" ", 1)
        user.details.first_name = parts[0]
        user.details.last_name = parts[1] if len(parts) > 1 else ""

    # Handle monetary balance update on UserDetails (optional)
    if has_balance_update:
        try:
            balance_value = float(data["balance"])
            if balance_value < 0:
                return jsonify({"error": "Balance cannot be negative"}), 400
            user.details.balance = balance_value
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid balance value"}), 400

    # Handle token balance update (UserTokenBalance — separate model)
    if "token_balance" in data:
        try:
            token_value = int(data["token_balance"])
            if token_value < 0:
                return jsonify({"error": "Token balance cannot be negative"}), 400
            tb = db.session.query(UserTokenBalance).filter_by(user_id=user.id).first()
            if tb:
                tb.balance = token_value
            else:
                tb = UserTokenBalance(user_id=user.id, balance=token_value)
                db.session.add(tb)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid token balance value"}), 400

    saved_user = user_repo.save(user)

    return jsonify({"user": saved_user.to_dict()}), 200


@admin_users_bp.route("/<user_id>/roles", methods=["PUT"])
@require_auth
@require_admin
@require_permission("users.manage")
def update_user_roles(user_id):
    """
    Update user roles.

    Args:
        user_id: UUID of the user

    Body:
        - roles: list of strings (required)

    Returns:
        200: Updated user
        400: Validation error
        404: User not found
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    roles = data.get("roles", [])

    if not roles:
        return jsonify({"error": "At least one role is required"}), 400

    # For now, use the first role (single-role model)
    # TODO: Implement multi-role support in User model
    try:
        user.role = UserRole(roles[0])
    except ValueError:
        return jsonify({"error": f"Invalid role: {roles[0]}"}), 400

    saved_user = user_repo.save(user)

    return jsonify({"user": saved_user.to_dict(), "message": "Roles updated"}), 200


@admin_users_bp.route("/<user_id>/suspend", methods=["POST"])
@require_auth
@require_admin
@require_permission("users.manage")
def suspend_user(user_id):
    """
    Suspend a user.

    Args:
        user_id: UUID of the user

    Returns:
        200: User suspended
        404: User not found
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    user.status = UserStatus.SUSPENDED
    saved_user = user_repo.save(user)

    return (
        jsonify(
            {"user": saved_user.to_dict(), "message": "User suspended successfully"}
        ),
        200,
    )


@admin_users_bp.route("/<user_id>/activate", methods=["POST"])
@require_auth
@require_admin
@require_permission("users.manage")
def activate_user(user_id):
    """
    Activate a suspended user.

    Args:
        user_id: UUID of the user

    Returns:
        200: User activated
        404: User not found
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    user.status = UserStatus.ACTIVE
    saved_user = user_repo.save(user)

    return (
        jsonify(
            {"user": saved_user.to_dict(), "message": "User activated successfully"}
        ),
        200,
    )


@admin_users_bp.route("/<user_id>/deletion-info", methods=["GET"])
@require_auth
@require_admin
@require_permission("users.view")
def get_deletion_info(user_id):
    """
    Get information about what will be deleted if user is deleted.

    Args:
        user_id: UUID of the user

    Returns:
        200: Deletion info with cascade counts
        404: User not found
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Check what will be deleted
    from vbwd.repositories.invoice_repository import InvoiceRepository
    from vbwd.repositories.subscription_repository import SubscriptionRepository

    invoice_repo = InvoiceRepository(db.session)
    subscription_repo = SubscriptionRepository(db.session)

    invoices = invoice_repo.find_by_user(user_id)
    subscriptions = subscription_repo.find_by_user(user_id)

    return (
        jsonify(
            {
                "user_id": str(user.id),
                "email": user.email,
                "has_cascade_dependencies": len(invoices) > 0 or len(subscriptions) > 0,
                "invoice_count": len(invoices),
                "subscription_count": len(subscriptions),
            }
        ),
        200,
    )


@admin_users_bp.route("/<user_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("users.manage")
def delete_user(user_id):
    """
    Delete a user completely.

    Body (optional):
        - force: bool (if true, cascade delete all dependencies including invoices and subscriptions)

    Args:
        user_id: UUID of the user

    Returns:
        200: User deleted successfully
        404: User not found
        409: User has invoices/subscriptions and force delete not requested
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    force_delete = data.get("force", False)

    # Check if user has invoices or subscriptions
    from vbwd.repositories.invoice_repository import InvoiceRepository
    from vbwd.repositories.subscription_repository import SubscriptionRepository

    invoice_repo = InvoiceRepository(db.session)
    subscription_repo = SubscriptionRepository(db.session)

    invoices = invoice_repo.find_by_user(user_id)
    subscriptions = subscription_repo.find_by_user(user_id)

    has_dependencies = len(invoices) > 0 or len(subscriptions) > 0

    if has_dependencies and not force_delete:
        error_msg = (
            f"Cannot delete user with {len(invoices)} invoice(s) and "
            f"{len(subscriptions)} subscription(s). User has transaction history."
        )
        return (
            jsonify(
                {
                    "error": error_msg,
                    "has_dependencies": True,
                    "invoice_count": len(invoices),
                    "subscription_count": len(subscriptions),
                }
            ),
            409,
        )

    # Delete user (cascade delete is handled by database FK constraints with ondelete="CASCADE")
    user_repo.delete(user_id)

    return jsonify({"message": "User deleted successfully"}), 200


@admin_users_bp.route("/<user_id>/addons", methods=["GET"])
@require_auth
@require_admin
@require_permission("users.view")
def get_user_addons(user_id):
    """
    Get user's add-on subscriptions with invoice data.

    Args:
        user_id: UUID of the user

    Returns:
        200: List of addon subscriptions with invoice info
        404: User not found
    """
    user_repo = UserRepository(db.session)
    user = user_repo.find_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    container = current_app.container
    addon_sub_repo = container.addon_subscription_repository()
    invoice_repo = container.invoice_repository()

    addon_subs = addon_sub_repo.find_by_user(
        UUID(user_id) if isinstance(user_id, str) else user_id
    )

    result = []
    for addon_sub in addon_subs:
        data = {
            "id": str(addon_sub.id),
            "addon_name": addon_sub.addon.name if addon_sub.addon else "Unknown",
            "status": addon_sub.status.value,
            "starts_at": addon_sub.starts_at.isoformat()
            if addon_sub.starts_at
            else None,
            "expires_at": addon_sub.expires_at.isoformat()
            if addon_sub.expires_at
            else None,
            "created_at": addon_sub.created_at.isoformat()
            if addon_sub.created_at
            else None,
            "invoice_status": None,
            "first_invoice": None,
            "last_invoice": None,
        }

        if addon_sub.invoice_id:
            invoice = invoice_repo.find_by_id(addon_sub.invoice_id)
            if invoice:
                invoice_data = {
                    "id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "created_at": invoice.invoiced_at.isoformat()
                    if invoice.invoiced_at
                    else None,
                }
                data["invoice_status"] = invoice.status.value
                data["first_invoice"] = invoice_data
                data["last_invoice"] = invoice_data

        result.append(data)

    return jsonify({"addon_subscriptions": result}), 200


# ============================================================================
