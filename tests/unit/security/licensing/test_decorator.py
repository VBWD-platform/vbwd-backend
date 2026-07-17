"""``@requires_license`` gates on coverage and stamps introspectable markers."""
from flask import Flask, g, jsonify

from vbwd.security.licensing.decorator import (
    LICENSED_FEATURE_MARKER,
    REQUIRES_LICENSE_MARKER,
    requires_license,
)
from vbwd.security.route_audit import inspect_license


class _StubContext:
    def __init__(self, covered):
        self._covered = covered

    def has_feature(self, feature):
        return self._covered


def _app(required, context):
    app = Flask(__name__)
    app.config["LICENSE_REQUIRED"] = required
    app.license_context = context  # type: ignore[attr-defined]

    @app.before_request
    def _bind_license():
        g.license = app.license_context

    @app.route("/gated")
    @requires_license(feature="marketplace")
    def gated():
        return jsonify({"ok": True})

    return app


def test_uncovered_feature_returns_402_when_required():
    app = _app(required=True, context=_StubContext(covered=False))
    response = app.test_client().get("/gated")
    assert response.status_code == 402
    assert response.get_json()["feature"] == "marketplace"


def test_covered_feature_passes_when_required():
    app = _app(required=True, context=_StubContext(covered=True))
    response = app.test_client().get("/gated")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_not_required_is_inert_even_when_uncovered():
    app = _app(required=False, context=_StubContext(covered=False))
    response = app.test_client().get("/gated")
    assert response.status_code == 200


def test_markers_are_stamped_and_introspectable():
    @requires_license(feature="marketplace")
    def view():
        return "ok"

    assert getattr(view, REQUIRES_LICENSE_MARKER) is True
    assert getattr(view, LICENSED_FEATURE_MARKER) == "marketplace"
    requires_license_flag, feature = inspect_license(view)
    assert requires_license_flag is True
    assert feature == "marketplace"
