"""Admin user management routes."""
from flask import Blueprint, current_app, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_admin, require_auth, require_permission
from vbwd.models.enums import UserRole, UserStatus
from vbwd.repositories.user_details_repository import UserDetailsRepository
from vbwd.repositories.user_repository import UserRepository

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
    # S23 — body shape unchanged; logic moved to UserService.admin_create.
    from vbwd.services.user_service import AdminUserUpdateError, UserService

    payload = request.get_json() or {}
    service = UserService(
        user_repository=UserRepository(db.session),
        user_details_repository=UserDetailsRepository(db.session),
    )

    try:
        created_user = service.admin_create(payload, db.session)
    except AdminUserUpdateError as validation_error:
        message = str(validation_error)
        # Email-collision is a 409 conflict; everything else is 400.
        status_code = 409 if "already exists" in message else 400
        return jsonify({"error": message}), status_code

    # Fire user:created event (optional path — logs and continues if absent).
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
    except Exception as dispatch_error:  # noqa: BLE001 — optional event path
        import logging

        logging.getLogger(__name__).debug(
            "user:created event dispatch skipped: %s", dispatch_error
        )

    response = {
        "id": str(created_user.id),
        "email": created_user.email,
        "status": created_user.status.value,
        "role": created_user.role.value,
        "created_at": (
            created_user.created_at.isoformat() if created_user.created_at else None
        ),
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
    # S22 — shared pagination helper.
    from vbwd.utils.pagination import parse_pagination_params

    limit, offset = parse_pagination_params(request)
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
    # S23 — body shape unchanged; logic moved to UserService.admin_update.
    from vbwd.services.user_service import AdminUserUpdateError, UserService

    payload = request.get_json() or {}
    service = UserService(
        user_repository=UserRepository(db.session),
        user_details_repository=UserDetailsRepository(db.session),
    )
    try:
        saved_user = service.admin_update(user_id, payload, db.session)
    except AdminUserUpdateError as validation_error:
        return jsonify({"error": str(validation_error)}), 400

    if saved_user is None:
        return jsonify({"error": "User not found"}), 404
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

    # Check what will be deleted. Core contributes its own dependencies
    # (invoices); plugins contribute theirs (e.g. subscriptions) via the
    # deletion-dependency registry, so core names no plugin domain.
    from vbwd.repositories.invoice_repository import InvoiceRepository
    from vbwd.services.deletion_dependency_registry import (
        resolve_deletion_dependencies,
    )

    invoice_repo = InvoiceRepository(db.session)

    invoices = invoice_repo.find_by_user(user_id)
    dependencies = []
    if len(invoices) > 0:
        dependencies.append(
            {"type": "invoice", "count": len(invoices), "label": "Invoices"}
        )
    dependencies.extend(resolve_deletion_dependencies(user.id))

    return (
        jsonify(
            {
                "user_id": str(user.id),
                "email": user.email,
                "has_cascade_dependencies": len(dependencies) > 0,
                "dependencies": dependencies,
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

    # DELETE often arrives without a body / JSON content-type. Use
    # silent=True so a missing or non-JSON body yields {} instead of
    # Flask raising 415 Unsupported Media Type before `or {}` applies.
    data = request.get_json(silent=True) or {}
    force_delete = data.get("force", False)

    # Check if user has invoices or subscriptions
    from vbwd.repositories.invoice_repository import InvoiceRepository
    from vbwd.services.subscription_read_model import (
        resolve_subscription_read_model,
    )

    invoice_repo = InvoiceRepository(db.session)

    invoices = invoice_repo.find_by_user(user_id)
    invoice_count = len(invoices)
    subscription_count = resolve_subscription_read_model().count_user_subscriptions(
        user_id
    )

    has_dependencies = invoice_count > 0 or subscription_count > 0

    if has_dependencies and not force_delete:
        error_msg = (
            f"Cannot delete user with {invoice_count} invoice(s) and "
            f"{subscription_count} subscription(s). User has transaction history."
        )
        return (
            jsonify(
                {
                    "error": error_msg,
                    "has_dependencies": True,
                    "invoice_count": invoice_count,
                    "subscription_count": subscription_count,
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

    from vbwd.services.subscription_read_model import (
        resolve_subscription_read_model,
    )

    result = resolve_subscription_read_model().user_addon_subscriptions(user_id)

    return jsonify({"addon_subscriptions": result}), 200


# ============================================================================
