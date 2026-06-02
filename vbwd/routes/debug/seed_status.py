"""``GET /api/v1/_seed_status`` — per-plugin seed status (S30 slice 2).

Diffs the enabled plugin set (from the plugin manager) against the
``vbwd_plugin_seed_marker`` rows so the load-test harness can assert
``unseeded == []`` after its seed step. Debug-gated.
"""
from datetime import datetime
from typing import Optional

from flask import Blueprint, current_app, jsonify

from vbwd.extensions import db
from vbwd.middleware.debug import require_debug_enabled
from vbwd.repositories.seed_marker_repository import SeedMarkerRepository


def read_seed_marker(plugin_name: str) -> Optional[datetime]:
    """Return the seed timestamp for ``plugin_name`` or ``None``.

    Thin wrapper over the repository so the route stays declarative and the
    DB access has a single seam to stub in tests.
    """
    return SeedMarkerRepository(db.session).get_populated_at(plugin_name)


def register_seed_status(debug_bp: Blueprint) -> None:
    """Attach the ``/_seed_status`` handler to the debug blueprint."""

    @debug_bp.route("/_seed_status", methods=["GET"])
    @require_debug_enabled
    def seed_status():
        """Per-plugin seed status. Debug-only."""
        plugin_manager = getattr(current_app, "plugin_manager")
        status = {"seeded": [], "unseeded": [], "populated_at": {}}
        for plugin in plugin_manager.get_enabled_plugins():
            plugin_name = plugin.metadata.name
            populated_at = read_seed_marker(plugin_name)
            if populated_at is None:
                status["unseeded"].append(plugin_name)
            else:
                status["seeded"].append(plugin_name)
                status["populated_at"][plugin_name] = populated_at.isoformat()
        return jsonify(status)
