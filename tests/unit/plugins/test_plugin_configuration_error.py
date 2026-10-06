"""S152-00c C1 — fatal plugin configuration (``PluginConfigurationError``).

A plugin's ``validate_environment()`` may raise ``PluginConfigurationError`` for
a fatal misconfiguration. At boot (``load_persisted_state``) that error is never
swallowed, so ``create_app()`` fails and the process exits non-zero. Disabled
plugins are not validated, and every other init failure keeps today's
log-and-skip behaviour (Liskov guard).

Fixtures are fake plugins named ``fake_*`` only — core stays agnostic.
"""
from unittest.mock import patch

import pytest

from vbwd.plugins.base import BasePlugin, PluginMetadata, PluginStatus
from vbwd.plugins.config_store import PluginConfigEntry, PluginConfigStore
from vbwd.plugins.errors import PluginConfigurationError
from vbwd.plugins.manager import PluginManager

MISCONFIGURATION_MESSAGE = (
    "fake_misconfigured: FAKE_MODE is 'bogus' — set FAKE_MODE to 'on' or 'off'"
)


class FakePlugin(BasePlugin):
    """A minimal fake plugin; subclasses override one hook each."""

    def __init__(self, name: str):
        super().__init__()
        self._name = name
        self.enable_hook_calls = 0

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=self._name,
            version="1.0.0",
            author="Test",
            description="Fake plugin",
        )

    def on_enable(self) -> None:
        self.enable_hook_calls += 1


class FakeMisconfiguredPlugin(FakePlugin):
    """Raises a fatal configuration error from ``validate_environment``."""

    def validate_environment(self) -> None:
        raise PluginConfigurationError(MISCONFIGURATION_MESSAGE)


class FakeBrokenInitializePlugin(FakePlugin):
    """Raises an ordinary (non-configuration) error while initialising."""

    def initialize(self, config=None) -> None:
        if config:
            raise RuntimeError("fake_broken_initialize: boom")
        super().initialize(config)


class InMemoryConfigStore(PluginConfigStore):
    """Persisted plugin state held in a dict: ``{name: (status, config)}``."""

    def __init__(self, entries):
        self._entries = dict(entries)

    def get_enabled(self):
        return [
            PluginConfigEntry(plugin_name=name, status=status, config=config)
            for name, (status, config) in self._entries.items()
            if status == "enabled"
        ]

    def save(self, plugin_name, status, config=None, version=None):
        self._entries[plugin_name] = (status, config or {})

    def get_by_name(self, plugin_name):
        if plugin_name not in self._entries:
            return None
        status, config = self._entries[plugin_name]
        return PluginConfigEntry(plugin_name=plugin_name, status=status, config=config)

    def get_all(self):
        return [self.get_by_name(name) for name in self._entries]

    def get_config(self, plugin_name):
        return self._entries.get(plugin_name, ("disabled", {}))[1]

    def save_config(self, plugin_name, config):
        status = self._entries.get(plugin_name, ("disabled", {}))[0]
        self._entries[plugin_name] = (status, config)


def _manager_with(plugins, persisted_entries) -> PluginManager:
    manager = PluginManager(config_repo=InMemoryConfigStore(persisted_entries))
    for plugin in plugins:
        manager.register_plugin(plugin)
        manager.initialize_plugin(plugin.metadata.name)
    return manager


def _discovered_plugins():
    discovery_manager = PluginManager()
    discovery_manager.discover("plugins")
    return discovery_manager.get_all_plugins()


def test_configuration_error_is_not_value_error():
    """Existing ``except ValueError`` callers must never swallow it."""
    assert issubclass(PluginConfigurationError, Exception)
    assert not issubclass(PluginConfigurationError, ValueError)


def test_base_validate_environment_is_noop():
    assert FakePlugin("fake_plain").validate_environment() is None


@pytest.mark.parametrize(
    "plugin",
    _discovered_plugins(),
    ids=lambda plugin: plugin.metadata.name,
)
def test_every_plugin_validates_cleanly_in_the_default_environment(plugin):
    """Every discovered plugin passes ``validate_environment()`` in the default
    test environment, so adding the hook never breaks an existing boot.

    Plugins MAY override the hook (e.g. to reject an invalid env value); the
    contract is only that the default environment is valid.
    """
    assert plugin.validate_environment() is None


def test_configuration_error_in_enabled_plugin_fails_load_persisted_state():
    misconfigured = FakeMisconfiguredPlugin("fake_misconfigured")
    manager = _manager_with(
        [misconfigured], {"fake_misconfigured": ("enabled", {"key": "value"})}
    )

    with pytest.raises(PluginConfigurationError, match="FAKE_MODE"):
        manager.load_persisted_state()

    assert misconfigured.status != PluginStatus.ENABLED
    assert misconfigured.enable_hook_calls == 0


def test_configuration_error_in_enabled_plugin_fails_create_app():
    """``create_app`` does not swallow the error raised during plugin boot."""
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    with patch.object(
        PluginManager,
        "load_persisted_state",
        side_effect=PluginConfigurationError(MISCONFIGURATION_MESSAGE),
    ):
        with pytest.raises(PluginConfigurationError, match="FAKE_MODE"):
            create_app(
                {
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": get_database_url(),
                }
            )


def test_configuration_error_in_disabled_plugin_is_ignored():
    misconfigured = FakeMisconfiguredPlugin("fake_misconfigured")
    healthy = FakePlugin("fake_healthy")
    manager = _manager_with(
        [misconfigured, healthy],
        {
            "fake_misconfigured": ("disabled", {}),
            "fake_healthy": ("enabled", {}),
        },
    )

    manager.load_persisted_state()

    assert healthy.status == PluginStatus.ENABLED
    assert misconfigured.status == PluginStatus.INITIALIZED


def test_other_init_exceptions_still_log_and_skip(caplog):
    broken = FakeBrokenInitializePlugin("fake_broken_initialize")
    healthy = FakePlugin("fake_healthy")
    manager = _manager_with(
        [broken, healthy],
        {
            "fake_broken_initialize": ("enabled", {"key": "value"}),
            "fake_healthy": ("enabled", {}),
        },
    )

    manager.load_persisted_state()

    assert broken.status != PluginStatus.ENABLED
    assert healthy.status == PluginStatus.ENABLED
    assert "fake_broken_initialize" in caplog.text


def test_runtime_enable_plugin_with_configuration_error_stays_disabled():
    misconfigured = FakeMisconfiguredPlugin("fake_misconfigured")
    manager = _manager_with([misconfigured], {})

    with pytest.raises(PluginConfigurationError, match="FAKE_MODE"):
        manager.enable_plugin("fake_misconfigured")

    assert misconfigured.status == PluginStatus.INITIALIZED
    assert misconfigured.enable_hook_calls == 0
    assert manager.get_enabled_plugins() == []
