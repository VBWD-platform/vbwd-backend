"""Permission and feature guard decorators."""
from functools import wraps
from typing import Callable, Any
from flask import current_app, jsonify, g
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request


def require_permission(*permissions: str) -> Callable:
    """
    Decorator to require at least one of the specified permissions.

    Usage:
        @require_permission("users.view", "users.manage")
        def list_users():
            ...

    Args:
        permissions: Permission names (any one required)

    Returns:
        Decorated function
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            verify_jwt_in_request()
            user_id = get_jwt_identity()

            rbac = getattr(current_app, "container").rbac_service()

            if not rbac.has_any_permission(user_id, list(permissions)):
                return (
                    jsonify(
                        {
                            "error": "Insufficient permissions",
                            "required": list(permissions),
                            "code": "PERMISSION_DENIED",
                        }
                    ),
                    403,
                )

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_all_permissions(*permissions: str) -> Callable:
    """
    Decorator to require ALL specified permissions.

    Usage:
        @require_all_permissions("users.view", "reports.view")
        def user_reports():
            ...

    Args:
        permissions: Permission names (all required)

    Returns:
        Decorated function
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            verify_jwt_in_request()
            user_id = get_jwt_identity()

            rbac = getattr(current_app, "container").rbac_service()

            if not rbac.has_all_permissions(user_id, list(permissions)):
                return (
                    jsonify(
                        {
                            "error": "Insufficient permissions",
                            "required": list(permissions),
                            "code": "PERMISSION_DENIED",
                        }
                    ),
                    403,
                )

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_role(*roles: str) -> Callable:
    """
    Decorator to require at least one of the specified roles.

    Usage:
        @require_role("admin", "moderator")
        def admin_action():
            ...

    Args:
        roles: Role names (any one required)

    Returns:
        Decorated function
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            verify_jwt_in_request()
            user_id = get_jwt_identity()

            rbac = getattr(current_app, "container").rbac_service()
            user_roles = rbac.get_user_roles(user_id)

            if not any(role in user_roles for role in roles):
                return (
                    jsonify(
                        {
                            "error": "Insufficient role",
                            "required": list(roles),
                            "code": "ROLE_REQUIRED",
                        }
                    ),
                    403,
                )

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_feature(feature_name: str) -> Callable:
    """
    Decorator to require a subscription feature.

    Usage:
        @require_feature("advanced_analytics")
        def analytics_dashboard():
            ...

    Args:
        feature_name: Name of required feature

    Returns:
        Decorated function
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            verify_jwt_in_request()
            user_id = get_jwt_identity()

            from vbwd.services.entitlement import resolve_entitlement_provider

            guard = resolve_entitlement_provider()

            if not guard.is_feature_allowed(user_id, feature_name):
                return (
                    jsonify(
                        {
                            "error": "Feature not available",
                            "feature": feature_name,
                            "upgrade_required": True,
                            "code": "FEATURE_UNAVAILABLE",
                        }
                    ),
                    403,
                )

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def check_usage_limit(feature_name: str, amount: int = 1) -> Callable:
    """
    Decorator to check and increment usage limit.

    Usage:
        @check_usage_limit("api_calls", 1)
        def api_endpoint():
            ...

    Args:
        feature_name: Name of feature to track
        amount: Amount to increment (default 1)

    Returns:
        Decorated function
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            verify_jwt_in_request()
            user_id = get_jwt_identity()

            from vbwd.services.entitlement import resolve_entitlement_provider

            guard = resolve_entitlement_provider()
            allowed, remaining = guard.check_usage_limit(user_id, feature_name, amount)

            if not allowed:
                return (
                    jsonify(
                        {
                            "error": "Usage limit exceeded",
                            "feature": feature_name,
                            "remaining": remaining,
                            "code": "LIMIT_EXCEEDED",
                        }
                    ),
                    429,
                )

            # Store remaining in g for potential use in route
            g.usage_remaining = remaining

            return fn(*args, **kwargs)

        return wrapper

    return decorator
