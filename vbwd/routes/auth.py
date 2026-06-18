"""Authentication routes."""
from flask import Blueprint, request, jsonify, current_app
from marshmallow import ValidationError
from vbwd.schemas.auth_schemas import (
    RegisterRequestSchema,
    LoginRequestSchema,
    AuthResponseSchema,
)
from vbwd.extensions import limiter
from vbwd.events.security_events import (
    PasswordResetRequestEvent,
    PasswordResetExecuteEvent,
)
from vbwd.services.core_rate_limits_store import get_auth_rate_limit

# Create blueprint
auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

# Initialize schemas
register_schema = RegisterRequestSchema()
login_schema = LoginRequestSchema()
auth_response_schema = AuthResponseSchema()


@auth_bp.route("/register", methods=["POST"])
@limiter.limit(lambda: get_auth_rate_limit("register"))
def register():
    """Register a new user.

    ---
    Request body:
        {
            "email": "user@example.com",
            "password": "SecurePassword123!"
        }

    Returns:
        200: {
            "success": true,
            "token": "jwt_token_here",
            "user_id": "uuid-here"
        }
        400: {
            "success": false,
            "error": "Error message"
        }
    """
    try:
        # Validate request data
        data = register_schema.load(request.json)
    except ValidationError as err:
        return jsonify({"success": False, "error": str(err.messages)}), 400

    # S08 — pull service from container, not inline construction.
    auth_service = current_app.container.auth_service()

    # Register user
    result = auth_service.register(email=data["email"], password=data["password"])

    # Return response
    if result.success:
        return jsonify(auth_response_schema.dump(result)), 200
    else:
        return jsonify(auth_response_schema.dump(result)), 400


@auth_bp.route("/login", methods=["POST"])
@limiter.limit(lambda: get_auth_rate_limit("login"))
def login():
    """Login a user.

    ---
    Request body:
        {
            "email": "user@example.com",
            "password": "SecurePassword123!"
        }

    Returns:
        200: {
            "success": true,
            "token": "jwt_token_here",
            "user_id": "uuid-here"
        }
        400: {
            "success": false,
            "error": "Error message"
        }
    """
    try:
        # Validate request data
        data = login_schema.load(request.json)
    except ValidationError as err:
        return jsonify({"success": False, "error": str(err.messages)}), 400

    # S08 — pull service from container, not inline construction.
    auth_service = current_app.container.auth_service()

    # Login user
    result = auth_service.login(email=data["email"], password=data["password"])

    # Return response
    if result.success:
        return jsonify(auth_response_schema.dump(result)), 200
    else:
        return jsonify(auth_response_schema.dump(result)), 401


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Logout a user.

    This endpoint invalidates the user's session by clearing client-side token.
    The JWT token validation happens on the client side.

    Returns:
        200: {"message": "Logged out successfully"}
    """
    return jsonify({"message": "Logged out successfully"}), 200


@auth_bp.route("/check-email", methods=["GET"])
@limiter.limit(lambda: get_auth_rate_limit("check_email"))
def check_email():
    """Check if an email address is already registered.

    ---
    Query params:
        email: Email address to check

    Returns:
        200: {"exists": true/false}
        400: {"error": "Email required"}
    """
    email = request.args.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Email required"}), 400

    # S08 — pull repo from container, not inline construction.
    user_repo = current_app.container.user_repository()
    user = user_repo.find_by_email(email)

    return jsonify({"exists": user is not None})


@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit(lambda: get_auth_rate_limit("forgot_password"))
def forgot_password():
    """
    Request password reset.

    Flow: Route → emit event → Dispatcher → Handler → Service → DB

    ---
    Request body:
        {
            "email": "user@example.com"
        }

    Returns:
        200: {
            "message": "If email exists, reset link sent"
        }
        400: {
            "error": "Email required"
        }
    """
    data = request.get_json() or {}
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email required"}), 400

    # Get dispatcher from container
    try:
        dispatcher = current_app.container.event_dispatcher()

        # Emit event - handler will do the work
        result = dispatcher.emit(
            PasswordResetRequestEvent(email=email, request_ip=request.remote_addr)
        )

        # Always return success (don't reveal if email exists)
        return jsonify(result.data or {"message": "If email exists, reset link sent"})
    except Exception:
        # Even on error, don't reveal information
        return jsonify({"message": "If email exists, reset link sent"})


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit(lambda: get_auth_rate_limit("reset_password"))
def reset_password():
    """
    Execute password reset with token.

    Flow: Route → emit event → Dispatcher → Handler → Service → DB

    ---
    Request body:
        {
            "token": "reset_token_here",
            "new_password": "NewSecurePassword123!"
        }

    Returns:
        200: {
            "message": "Password reset successful"
        }
        400: {
            "error": "Error message"
        }
    """
    data = request.get_json() or {}
    token = data.get("token")
    new_password = data.get("new_password")

    if not token or not new_password:
        return jsonify({"error": "Token and new password required"}), 400

    # Get dispatcher from container
    try:
        dispatcher = current_app.container.event_dispatcher()

        # Emit event - handler will do the work
        result = dispatcher.emit(
            PasswordResetExecuteEvent(
                token=token, new_password=new_password, reset_ip=request.remote_addr
            )
        )

        if result.success:
            return jsonify(result.data or {"message": "Password reset successful"})
        return jsonify({"error": result.error}), 400
    except Exception:
        return jsonify({"error": "Password reset failed"}), 400
