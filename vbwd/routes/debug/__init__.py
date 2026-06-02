"""Debug-only introspection endpoints (S30).

A single blueprint carries the load-test affordances (``/api/v1/_routes``,
``/api/v1/_seed_status``). Every route is gated by ``require_debug_enabled``
so the whole surface is hidden in production by default.
"""
from flask import Blueprint

from vbwd.routes.debug.routes_catalog import register_routes_catalog
from vbwd.routes.debug.seed_status import register_seed_status

debug_bp = Blueprint("debug", __name__, url_prefix="/api/v1")

register_routes_catalog(debug_bp)
register_seed_status(debug_bp)

__all__ = ["debug_bp"]
