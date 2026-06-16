"""``GET /api/v1/_routes`` — route-catalog introspection (S30 slice 1).

Lists every registered route with its method, path template, endpoint,
auth requirement, and required permission (when known). The load-test
harness reads this to fail fast on URL drift instead of discovering a typo
two minutes into a threshold-breach failure.

Debug-gated via ``require_debug_enabled`` — see ``vbwd/middleware/debug.py``.
"""
from flask import Blueprint, current_app, jsonify

from vbwd.middleware.debug import require_debug_enabled
from vbwd.security.route_audit import audit_routes


def register_routes_catalog(debug_bp: Blueprint) -> None:
    """Attach the ``/_routes`` handler to the debug blueprint."""

    @debug_bp.route("/_routes", methods=["GET"])
    @require_debug_enabled
    def list_routes():
        """List every registered route. Debug-only.

        Reuses the shared ``route_audit`` introspection helper (DRY) so the
        catalog, the route-exposure oracle, and the prod-readiness command all
        read the same per-route protection facts.
        """
        catalog = []
        for route in audit_routes(current_app):
            for method in route.methods:
                catalog.append(
                    {
                        "method": method,
                        "path": route.path,
                        "endpoint": route.endpoint,
                        "auth_required": route.requires_auth,
                        "permission": route.required_permission,
                    }
                )
        return jsonify({"routes": catalog})
