"""S137.1 boot-order oracle — the licence context must exist before plugins enable.

``PluginManager``'s licence gate reads the context injected at construction.
``create_app`` originally built the licence environment *after* enabling
plugins, so the gate would have read nothing on every boot. This pins that the
manager restoring persisted state already holds the app's licence context — a
regression is silent: the gate would simply stop seeing any licence.
"""
from flask import current_app

from vbwd.plugins.manager import PluginManager


def test_license_context_is_injected_before_plugins_are_enabled(monkeypatch):
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    observed = {}
    original_load = PluginManager.load_persisted_state

    def spy_load_persisted_state(self):
        observed["app_context"] = getattr(current_app, "license_context", None)
        observed["manager_context"] = self._license_context
        return original_load(self)

    monkeypatch.setattr(PluginManager, "load_persisted_state", spy_load_persisted_state)

    create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URL": "memory://",
        }
    )

    assert "app_context" in observed, "load_persisted_state was never called"
    assert observed["app_context"] is not None, (
        "plugins were enabled before app.license_context existed — the licence "
        "gate would read nothing"
    )
    assert observed["manager_context"] is observed["app_context"]
