"""Specs for the ``flask plugins`` CLI commands (S108.5)."""
from vbwd.plugins.base import BasePlugin, PluginMetadata
from vbwd.plugins.manager import PluginManager


class VersionedPlugin(BasePlugin):
    """Mock plugin with configurable version + dependencies."""

    def __init__(self, name, version="26.6", dependencies=None):
        super().__init__()
        self._name = name
        self._version = version
        self._dependencies = dependencies or []

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=self._name,
            version=self._version,
            author="Test",
            description="Test plugin",
            dependencies=self._dependencies,
        )


def _manager_with_too_old_email():
    """email v26.6 ENABLED; booking requires email>=26.7 (INITIALIZED)."""
    manager = PluginManager()
    email = VersionedPlugin("email", version="26.6")
    booking = VersionedPlugin("booking", dependencies=["email>=26.7"])
    for plugin in (email, booking):
        manager.register_plugin(plugin)
        manager.initialize_plugin(plugin.metadata.name)
    manager.enable_plugin("email")
    return manager


def test_enable_with_too_old_dependency_exits_nonzero(app, runner):
    """enable prints the version-specific reason and exits non-zero."""
    app.plugin_manager = _manager_with_too_old_email()

    result = runner.invoke(args=["plugins", "enable", "booking"])

    assert result.exit_code != 0
    assert "email>=26.7" in result.output
    assert "26.6" in result.output


def test_enable_with_satisfied_dependency_succeeds(app, runner):
    """enable succeeds (exit 0) when the dependency version satisfies."""
    manager = PluginManager()
    email = VersionedPlugin("email", version="26.7")
    booking = VersionedPlugin("booking", dependencies=["email>=26.7"])
    for plugin in (email, booking):
        manager.register_plugin(plugin)
        manager.initialize_plugin(plugin.metadata.name)
    manager.enable_plugin("email")
    app.plugin_manager = manager

    result = runner.invoke(args=["plugins", "enable", "booking"])

    assert result.exit_code == 0
    assert "enabled" in result.output


def test_list_shows_unmet_constraint(app, runner):
    """list shows the unmet dependency constraint for a blocked plugin."""
    app.plugin_manager = _manager_with_too_old_email()

    result = runner.invoke(args=["plugins", "list"])

    assert result.exit_code == 0
    assert "booking" in result.output
    assert "needs email>=26.7" in result.output
    assert "have 26.6" in result.output


def test_list_no_note_for_satisfied_plugin(app, runner):
    """list does not append a note for a plugin with satisfied deps."""
    manager = PluginManager()
    email = VersionedPlugin("email", version="26.7")
    manager.register_plugin(email)
    manager.initialize_plugin("email")
    manager.enable_plugin("email")
    app.plugin_manager = manager

    result = runner.invoke(args=["plugins", "list"])

    assert result.exit_code == 0
    assert "needs" not in result.output
