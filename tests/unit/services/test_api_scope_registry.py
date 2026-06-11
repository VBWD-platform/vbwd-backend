"""S52.2 — core API scope registry unit tests.

Mirrors ``permission_catalog``: collect core + each enabled plugin's declared
``api_scopes`` through the injected ``plugin_manager`` — never by importing a
plugin module. Core ships **zero** domain scopes.
"""
from types import SimpleNamespace

from vbwd.services.api_scope_registry import collect_api_scopes


class _FakePluginManager:
    def __init__(self, plugins):
        self._plugins = plugins

    def get_enabled_plugins(self):
        return self._plugins


def _plugin(name, api_scopes):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        api_scopes=api_scopes,
    )


def test_core_scope_list_is_always_empty():
    catalog = collect_api_scopes(plugin_manager=_FakePluginManager([]))
    assert catalog["core"] == []


def test_plugin_scopes_are_surfaced_under_plugin_name():
    scope = {
        "key": "demo:thing:do",
        "label": "Do the thing",
        "description": "...",
        "user_grantable": True,
    }
    manager = _FakePluginManager([_plugin("demoplug", [scope])])

    catalog = collect_api_scopes(plugin_manager=manager)

    assert catalog["demoplug"] == [scope]
    assert catalog["core"] == []


def test_plugin_without_api_scopes_is_skipped():
    manager = _FakePluginManager(
        [SimpleNamespace(metadata=SimpleNamespace(name="noscopes"))]
    )

    catalog = collect_api_scopes(plugin_manager=manager)

    assert "noscopes" not in catalog
    assert catalog == {"core": []}


def test_no_manager_returns_only_core():
    assert collect_api_scopes(plugin_manager=None, _resolve_app=False) == {"core": []}
