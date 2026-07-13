"""``@requires_license`` — the request-level license gate.

Mirrors the auth/permission marker pattern in ``vbwd/middleware/auth.py``:
stamps introspectable markers (so ``route_audit`` classifies the route as a
distinct protection class) and gates the request. An uncovered feature returns
**402 Payment Required**; a covered feature (or the open / not-required path,
where ``g.license`` is a ``NullLicenseContext`` whose ``has_feature`` is always
True) passes through. Degraded mode is honoured for free: the degraded context
simply reports the feature as uncovered.
"""
from functools import wraps

from flask import current_app, g, jsonify

# Marker attribute names — kept as named constants so the decorator and the
# route-exposure oracle agree on the exact strings (single source of truth).
REQUIRES_LICENSE_MARKER = "requires_license"
LICENSED_FEATURE_MARKER = "licensed_feature"

PAYMENT_REQUIRED_STATUS = 402


def requires_license(feature: str):
    """Gate a route on ``feature`` being covered by a held, active license.

    Usage::

        @some_bp.route("/thing")
        @require_auth
        @requires_license(feature="marketplace")
        def thing(): ...
    """

    def decorator(view_function):
        @wraps(view_function)
        def wrapper(*args, **kwargs):
            # CE never enforces (LICENSE_REQUIRED=false): the gate is inert.
            if not current_app.config.get("LICENSE_REQUIRED", False):
                return view_function(*args, **kwargs)
            context = getattr(g, "license", None)
            if context is None:
                context = getattr(current_app, "license_context", None)
            if context is None or context.has_feature(feature):
                return view_function(*args, **kwargs)
            return (
                jsonify(
                    {
                        "error": "License required",
                        "feature": feature,
                    }
                ),
                PAYMENT_REQUIRED_STATUS,
            )

        setattr(wrapper, REQUIRES_LICENSE_MARKER, True)
        setattr(wrapper, LICENSED_FEATURE_MARKER, feature)
        return wrapper

    return decorator
