"""Specs for the ``flask prod-readiness`` CLI command (S90, slice 4).

The command runs a pre-rollout checklist against the *running* app +
environment and exits 0 only if all HARD checks pass. Each item prints
✅ / ❌ / ⚠️; HARD failures flip the exit code, WARNINGS do not.

Hard checks: env=production, non-default secrets, debug endpoints off,
route-exposure clean, sanitized 500 handler, CORS not wildcard.
Warnings: log level info/debug (should be warning/error), demo/loadtest seed
markers present.

Tests invoke the command via Flask's ``app.test_cli_runner()`` so the command
sees the app's real config. ``FLASK_ENV`` is injected via monkeypatch.
"""
import pytest
from flask import Blueprint, jsonify

from vbwd.cli.prod_readiness import prod_readiness_command


def _build_app(config_overrides=None):
    """Boot the full app with prod-like config overrides for the test runner."""
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        # A production-correct baseline; individual tests inject one gap.
        "DEBUG": False,
        "SECRET_KEY": "a-real-rotated-secret-value-001",
        "JWT_SECRET_KEY": "a-real-rotated-jwt-value-002",
        "ENABLE_DEBUG_ENDPOINTS": False,
        "LOG_LEVEL": "warning",
    }
    if config_overrides:
        config.update(config_overrides)
    return create_app(config)


@pytest.fixture
def prod_env(monkeypatch):
    """Pretend the process is running with FLASK_ENV=production."""
    monkeypatch.setenv("FLASK_ENV", "production")


def _invoke(app):
    runner = app.test_cli_runner()
    return runner.invoke(prod_readiness_command)


def test_passes_on_a_correctly_configured_prod_app(prod_env):
    """A correctly-configured prod app exits 0 with all hard checks ✅."""
    app = _build_app()
    result = _invoke(app)
    assert result.exit_code == 0, result.output
    assert "PROD-READINESS" in result.output.upper()


def test_fails_when_not_production_environment(monkeypatch):
    """FLASK_ENV != production is a hard failure naming the item."""
    monkeypatch.setenv("FLASK_ENV", "development")
    app = _build_app({"DEBUG": True})
    result = _invoke(app)
    assert result.exit_code != 0
    assert "production" in result.output.lower()


def test_fails_when_debug_endpoints_enabled(prod_env):
    """ENABLE_DEBUG_ENDPOINTS truthy is a hard failure."""
    app = _build_app({"ENABLE_DEBUG_ENDPOINTS": True})
    result = _invoke(app)
    assert result.exit_code != 0
    assert "debug" in result.output.lower()


def test_fails_when_secret_key_is_dev_default(prod_env):
    """A dev-default secret key is a hard failure naming the item."""
    from vbwd.config import DEFAULT_SECRET_KEY

    app = _build_app({"SECRET_KEY": DEFAULT_SECRET_KEY})
    result = _invoke(app)
    assert result.exit_code != 0
    assert "secret" in result.output.lower()


def test_info_log_level_is_a_warning_not_a_hard_failure(prod_env):
    """An info log level prints ⚠️ but does NOT flip the exit code."""
    app = _build_app({"LOG_LEVEL": "info"})
    result = _invoke(app)
    assert result.exit_code == 0, result.output
    assert "⚠️" in result.output
    assert "log level" in result.output.lower()


def test_fails_on_an_unprotected_mutating_route(prod_env):
    """A registered unprotected mutating route is a hard failure (check #5)."""
    probe_bp = Blueprint("readiness_probe", __name__)

    @probe_bp.route("/api/v1/_readiness_probe", methods=["POST"])
    def _readiness_probe():  # pragma: no cover - introspected only
        return jsonify({"ok": True})

    app = _build_app()
    app.register_blueprint(probe_bp)
    result = _invoke(app)
    assert result.exit_code != 0
    assert "route" in result.output.lower()
    assert "_readiness_probe" in result.output


def test_fails_when_cors_is_wildcard(prod_env):
    """A wildcard CORS allowed-origins is a hard failure (check #8)."""
    app = _build_app({"CORS_ALLOWED_ORIGINS": "*"})
    result = _invoke(app)
    assert result.exit_code != 0
    assert "cors" in result.output.lower()


def test_summary_names_each_hard_failure(monkeypatch):
    """Multiple injected gaps each appear by name in the summary."""
    monkeypatch.setenv("FLASK_ENV", "development")
    from vbwd.config import DEFAULT_SECRET_KEY

    app = _build_app(
        {
            "DEBUG": True,
            "SECRET_KEY": DEFAULT_SECRET_KEY,
            "ENABLE_DEBUG_ENDPOINTS": True,
        }
    )
    result = _invoke(app)
    assert result.exit_code != 0
    lowered = result.output.lower()
    assert "production" in lowered
    assert "secret" in lowered
    assert "debug" in lowered
