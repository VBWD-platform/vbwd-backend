"""Specs for the shared debug-gate decorator ``require_debug_enabled``.

The two introspection endpoints (S30 slices 1 & 2) share this gate so the
debug-on/off behaviour lives in exactly one place (DRY). The gate reads
``current_app.config["ENABLE_DEBUG_ENDPOINTS"]`` at REQUEST time, not at
import/boot, so a pytest fixture can flip it per test.
"""
import pytest
from flask import Flask, jsonify

from vbwd.middleware.debug import require_debug_enabled


@pytest.fixture
def gated_app():
    """Minimal Flask app with one debug-gated route."""
    app = Flask(__name__)

    @app.route("/gated")
    @require_debug_enabled
    def gated_route():
        return jsonify({"ok": True})

    return app


def test_returns_404_when_flag_absent(gated_app):
    """Spec 1: with no ENABLE_DEBUG_ENDPOINTS config, the gate returns 404."""
    client = gated_app.test_client()
    response = client.get("/gated")
    assert response.status_code == 404


def test_returns_404_when_flag_false(gated_app):
    """Spec 2: ENABLE_DEBUG_ENDPOINTS is False -> 404 (prod-safe default)."""
    gated_app.config["ENABLE_DEBUG_ENDPOINTS"] = False
    client = gated_app.test_client()
    response = client.get("/gated")
    assert response.status_code == 404


def test_passes_through_when_flag_true(gated_app):
    """Spec 3: ENABLE_DEBUG_ENDPOINTS is True -> wrapped view runs (200)."""
    gated_app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    client = gated_app.test_client()
    response = client.get("/gated")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_flag_is_read_at_request_time_not_boot(gated_app):
    """Spec 4: flipping the config after app creation takes effect per request
    (read at request time, so fixtures can toggle it)."""
    client = gated_app.test_client()
    assert client.get("/gated").status_code == 404
    gated_app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    assert client.get("/gated").status_code == 200
    gated_app.config["ENABLE_DEBUG_ENDPOINTS"] = False
    assert client.get("/gated").status_code == 404
