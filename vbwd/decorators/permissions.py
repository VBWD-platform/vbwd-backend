"""Feature-entitlement guard decorators.

The permission/role guards (``require_auth``, ``require_permission``,
``require_admin``, ``require_user_permission``) live in
``vbwd/middleware/auth.py`` — that is the single, live authorization path.

The duplicate JWT-flavour ``require_permission`` / ``require_all_permissions``
/ ``require_role`` decorators that once lived here were dead (zero route
importers; they called ``RBACService`` check methods that nothing else used)
and were removed in S90 Slice 2 / S94 G4. What remains are the
entitlement-port hooks below, which resolve a generic
``IEntitlementProvider`` (so core stays agnostic of the subscription plugin).
"""
from functools import wraps
from typing import Callable, Any
from flask import jsonify, g
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request


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
