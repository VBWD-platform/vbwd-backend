"""Authentication middleware."""
from functools import wraps
from flask import request, jsonify, g
from vbwd.services.auth_service import AuthService
from vbwd.repositories.user_repository import UserRepository
from vbwd.extensions import db


def require_auth(f):
    """Decorator to require authentication for a route.

    Validates JWT token from Authorization header and loads user into g.user_id.

    Usage:
        @auth_bp.route('/protected')
        @require_auth
        def protected_route():
            user_id = g.user_id
            ...

    Returns:
        401: If token is missing or invalid
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Authorization header is required"}), 401

        # Extract token (format: "Bearer <token>")
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return jsonify({"error": "Invalid Authorization header format"}), 401

        token = parts[1]

        # Verify token
        user_repo = UserRepository(db.session)
        auth_service = AuthService(user_repository=user_repo)

        user_id = auth_service.verify_token(token)
        if not user_id:
            return jsonify({"error": "Invalid or expired token"}), 401

        # Verify user exists and is active
        user = user_repo.find_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 401

        if user.status.value != "ACTIVE":
            return jsonify({"error": "User account is not active"}), 401

        # Store user_id in Flask's g object for use in route
        g.user_id = user_id
        g.user = user

        return f(*args, **kwargs)

    return decorated_function


def require_admin(f):
    """Decorator to require admin panel access.

    Uses RBAC is_admin check (backward compatible with legacy UserRole enum).
    Must be used with @require_auth decorator.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, "user"):
            return jsonify({"error": "Authentication required"}), 401
        if not g.user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


def require_permission(*permissions):
    """Decorator to require specific permissions for a route.

    Checks all specified permissions — user must have ALL of them.
    Supports wildcards: "*" matches everything, "shop.*" matches all shop permissions.
    Must be used with @require_auth decorator.

    Usage:
        @require_auth
        @require_permission("shop.products.view")
        def list_products(): ...

        @require_auth
        @require_permission("shop.products.manage")
        def create_product(): ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, "user") or not g.user:
                return jsonify({"error": "Authentication required"}), 401
            for perm in permissions:
                if not g.user.has_permission(perm):
                    return (
                        jsonify(
                            {
                                "error": "Permission denied",
                                "required": perm,
                            }
                        ),
                        403,
                    )
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_user_permission(*permissions):
    """Decorator to require user-facing permissions.

    Checks user access levels (fe-user permissions).
    Must be used with @require_auth decorator.
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, "user") or not g.user:
                return jsonify({"error": "Authentication required"}), 401
            for perm in permissions:
                if not g.user.has_user_permission(perm):
                    return (
                        jsonify(
                            {
                                "error": "Permission denied",
                                "required": perm,
                            }
                        ),
                        403,
                    )
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def optional_auth(f):
    """Decorator to optionally authenticate a route.

    If token is provided and valid, loads user into g.user_id.
    If token is missing or invalid, continues without authentication.

    Usage:
        @api_bp.route('/public-or-private')
        @optional_auth
        def flexible_route():
            if hasattr(g, 'user_id'):
                # User is authenticated
                ...
            else:
                # User is not authenticated
                ...

    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            # No token, continue without auth
            return f(*args, **kwargs)

        # Extract token (format: "Bearer <token>")
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            # Invalid format, continue without auth
            return f(*args, **kwargs)

        token = parts[1]

        # Verify token
        user_repo = UserRepository(db.session)
        auth_service = AuthService(user_repository=user_repo)

        user_id = auth_service.verify_token(token)
        if user_id:
            # Valid token, load user
            user = user_repo.find_by_id(user_id)
            if user and user.status.value == "ACTIVE":
                g.user_id = user_id
                g.user = user

        # Continue with or without auth
        return f(*args, **kwargs)

    return decorated_function
