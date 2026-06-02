"""Specs for ``GET /api/v1/_seed_status`` — per-plugin seed status (S30
slice 2). Debug-gated; compares enabled plugins against seed-marker rows so
the load-test harness can assert ``unseeded == []`` after the seed step.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _enabled(name):
    """Build a plugin double whose metadata.name is ``name``."""
    plugin = MagicMock()
    plugin.metadata.name = name
    return plugin


def test_returns_404_when_debug_disabled(app):
    """Spec 1: with the flag off, the endpoint is hidden (404)."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = False
    client = app.test_client()
    response = client.get("/api/v1/_seed_status")
    assert response.status_code == 404


def test_all_enabled_plugins_unseeded_on_fresh_state(app):
    """Spec 2: with no markers, every enabled plugin is in ``unseeded``."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    app.plugin_manager.get_enabled_plugins = MagicMock(
        return_value=[_enabled("alpha"), _enabled("beta")]
    )
    with patch(
        "vbwd.routes.debug.seed_status.read_seed_marker",
        return_value=None,
    ):
        client = app.test_client()
        payload = client.get("/api/v1/_seed_status").get_json()

    assert set(payload["unseeded"]) == {"alpha", "beta"}
    assert payload["seeded"] == []
    assert payload["populated_at"] == {}


def test_seeded_plugin_moves_to_seeded_with_iso_timestamp(app):
    """Spec 3: a plugin with a marker appears in ``seeded`` and its
    ``populated_at`` is an ISO timestamp string."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    app.plugin_manager.get_enabled_plugins = MagicMock(
        return_value=[_enabled("alpha"), _enabled("beta")]
    )
    marker_time = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)

    def fake_marker(name):
        return marker_time if name == "alpha" else None

    with patch(
        "vbwd.routes.debug.seed_status.read_seed_marker",
        side_effect=fake_marker,
    ):
        client = app.test_client()
        payload = client.get("/api/v1/_seed_status").get_json()

    assert payload["seeded"] == ["alpha"]
    assert payload["unseeded"] == ["beta"]
    assert payload["populated_at"]["alpha"] == marker_time.isoformat()


def test_disabled_plugins_absent_from_both_lists(app):
    """Spec 4: only enabled plugins are reported; disabled ones never appear."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    app.plugin_manager.get_enabled_plugins = MagicMock(return_value=[_enabled("alpha")])
    with patch(
        "vbwd.routes.debug.seed_status.read_seed_marker",
        return_value=None,
    ):
        client = app.test_client()
        payload = client.get("/api/v1/_seed_status").get_json()

    all_listed = set(payload["seeded"]) | set(payload["unseeded"])
    assert all_listed == {"alpha"}
