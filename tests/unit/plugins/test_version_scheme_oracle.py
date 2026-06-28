"""Oracle: every registered plugin carries a parseable version + valid deps (S108.4).

Guards the locked version scheme:
  - ``PluginMetadata.version`` parses as a PEP 440 version.
  - every declared dependency parses via ``parse_dependency`` and references a
    plugin name that is actually registered.
  - ``checkout`` exposes real ``PluginMetadata``.
"""
import pytest
from packaging.version import InvalidVersion, Version

from vbwd.plugins.manager import PluginManager
from vbwd.plugins.versioning import parse_dependency


@pytest.fixture(scope="module")
def registered_plugins():
    manager = PluginManager()
    manager.discover("plugins")
    return manager.get_all_plugins()


@pytest.fixture(scope="module")
def registered_names(registered_plugins):
    return {plugin.metadata.name for plugin in registered_plugins}


def test_every_plugin_version_parses(registered_plugins):
    """Every plugin's metadata.version is a valid PEP 440 version."""
    for plugin in registered_plugins:
        version = plugin.metadata.version
        try:
            Version(version)
        except InvalidVersion:  # pragma: no cover - failure path
            pytest.fail(
                f"Plugin '{plugin.metadata.name}' has an unparseable "
                f"version '{version}'"
            )


def test_every_dependency_parses_and_is_known(registered_plugins, registered_names):
    """Every declared dependency parses and references a registered plugin."""
    for plugin in registered_plugins:
        for raw_dependency in plugin.metadata.dependencies or []:
            requirement = parse_dependency(raw_dependency)
            assert requirement.name in registered_names, (
                f"Plugin '{plugin.metadata.name}' declares dependency "
                f"'{raw_dependency}' on unknown plugin '{requirement.name}'"
            )


def test_checkout_exposes_metadata(registered_names):
    """The checkout plugin exposes real PluginMetadata (registered by name)."""
    assert "checkout" in registered_names
