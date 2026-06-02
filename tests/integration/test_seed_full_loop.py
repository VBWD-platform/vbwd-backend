"""Integration: ``flask seed`` writes real seed markers and the
``/api/v1/_seed_status`` endpoint reflects them against the live plugin set.

Uses the real ``vbwd_plugin_seed_marker`` table (created by the S30
migration) so the marker round-trip is exercised end-to-end.
"""
from unittest.mock import MagicMock

import pytest

from vbwd.repositories.seed_marker_repository import SeedMarkerRepository


@pytest.fixture
def app():
    """Real app against the integration Postgres DB."""
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "ENABLE_DEBUG_ENDPOINTS": True,
        "RATELIMIT_ENABLED": False,
    }
    return create_app(test_config)


def _stub_plugin(name):
    plugin = MagicMock()
    plugin.metadata.name = name
    plugin.populate = MagicMock(return_value={"created": 0, "skipped": 0, "errors": []})
    return plugin


def test_seed_then_status_reports_seeded(app):
    """seed <plugin> writes a marker; /_seed_status moves it to ``seeded``."""
    from vbwd.cli.seed import seed_command
    from vbwd.extensions import db

    plugin_name = "s30_int_marker"
    plugin = _stub_plugin(plugin_name)
    app.plugin_manager.get_enabled_plugins = MagicMock(return_value=[plugin])
    app.plugin_manager.get_plugin = MagicMock(
        side_effect=lambda name: plugin if name == plugin_name else None
    )

    with app.app_context():
        SeedMarkerRepository(db.session).clear(plugin_name)
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(seed_command, [plugin_name])
    assert result.exit_code == 0, result.output

    client = app.test_client()
    payload = client.get("/api/v1/_seed_status").get_json()
    assert plugin_name in payload["seeded"]
    assert plugin_name not in payload["unseeded"]
    assert plugin_name in payload["populated_at"]

    # Clean up the marker so the test is idempotent.
    with app.app_context():
        SeedMarkerRepository(db.session).clear(plugin_name)
        db.session.commit()
