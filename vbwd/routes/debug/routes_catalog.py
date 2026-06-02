"""``GET /api/v1/_routes`` — route-catalog introspection (S30 slice 1).

Lists every registered route with its method, path template, endpoint,
auth requirement, and required permission (when known). The load-test
harness reads this to fail fast on URL drift instead of discovering a typo
two minutes into a threshold-breach failure.

Debug-gated via ``require_debug_enabled`` — see ``vbwd/middleware/debug.py``.
"""
from typing import Any, Optional, Tuple

from flask import Blueprint, current_app, jsonify

from vbwd.middleware.debug import require_debug_enabled

# Implicit methods Werkzeug adds to every rule; not useful to the harness.
_IMPLICIT_METHODS = {"HEAD", "OPTIONS"}


def _iter_decorator_chain(view_func: Any):
    """Yield the view function and each ``@wraps``-linked inner function.

    Auth/permission decorators set markers on their own wrapper, so the
    relevant attribute may live on any link of the ``__wrapped__`` chain
    rather than only on the outermost view function.
    """
    seen = set()
    current = view_func
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__wrapped__", None)


def _inspect_auth(view_func: Any) -> Tuple[bool, Optional[str]]:
    """Return ``(auth_required, permission)`` by scanning the decorator chain."""
    auth_required = False
    permission: Optional[str] = None
    for link in _iter_decorator_chain(view_func):
        if getattr(link, "requires_auth", False):
            auth_required = True
        link_permission = getattr(link, "required_permission", None)
        if link_permission is not None:
            permission = link_permission
            auth_required = True
    return auth_required, permission


def register_routes_catalog(debug_bp: Blueprint) -> None:
    """Attach the ``/_routes`` handler to the debug blueprint."""

    @debug_bp.route("/_routes", methods=["GET"])
    @require_debug_enabled
    def list_routes():
        """List every registered route. Debug-only."""
        catalog = []
        for rule in current_app.url_map.iter_rules():
            view_func = current_app.view_functions.get(rule.endpoint)
            auth_required, permission = _inspect_auth(view_func)
            for method in sorted((rule.methods or set()) - _IMPLICIT_METHODS):
                catalog.append(
                    {
                        "method": method,
                        "path": str(rule),
                        "endpoint": rule.endpoint,
                        "auth_required": auth_required,
                        "permission": permission,
                    }
                )
        return jsonify({"routes": catalog})
