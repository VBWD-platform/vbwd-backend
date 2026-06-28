"""Tests for PluginManager persistence (config_repo integration)."""
import pytest
from unittest.mock import MagicMock
from vbwd.plugins.manager import PluginManager
from vbwd.plugins.base import BasePlugin, PluginMetadata, PluginStatus
from vbwd.plugins.config_store import PluginConfigStore, PluginConfigEntry


class MockPlugin(BasePlugin):
    """Mock plugin for testing."""

    def __init__(self, name: str):
        super().__init__()
        self._name = name

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=self._name,
            version="1.0.0",
            author="Test",
            description="Test plugin",
        )


class MockConfigStore(PluginConfigStore):
    """In-memory PluginConfigStore for testing."""

    def __init__(self):
        self._plugins = {}
        self._configs = {}

    def get_enabled(self):
        return [
            PluginConfigEntry(
                plugin_name=n, status="enabled", config=self._configs.get(n, {})
            )
            for n, s in self._plugins.items()
            if s == "enabled"
        ]

    def save(self, plugin_name, status, config=None, version=None):
        self._plugins[plugin_name] = status
        if config is not None:
            self._configs[plugin_name] = config

    def get_by_name(self, plugin_name):
        if plugin_name not in self._plugins:
            return None
        return PluginConfigEntry(
            plugin_name=plugin_name,
            status=self._plugins[plugin_name],
            config=self._configs.get(plugin_name, {}),
        )

    def get_all(self):
        return [
            PluginConfigEntry(plugin_name=n, status=s, config=self._configs.get(n, {}))
            for n, s in self._plugins.items()
        ]

    def get_config(self, plugin_name):
        return self._configs.get(plugin_name, {})

    def save_config(self, plugin_name, config):
        self._configs[plugin_name] = config


class TestPluginManagerPersistence:
    """Test persistence via config_repo."""

    @pytest.fixture
    def config_repo(self):
        return MagicMock(spec=PluginConfigStore)

    def test_enable_persists_to_repo(self, config_repo):
        """enable_plugin calls config_repo.save with 'enabled'."""
        manager = PluginManager(config_repo=config_repo)
        plugin = MockPlugin("test")
        manager.register_plugin(plugin)
        manager.initialize_plugin("test")

        manager.enable_plugin("test")

        config_repo.save.assert_called_once_with(
            "test", "enabled", plugin._config, version="1.0.0"
        )

    def test_disable_persists_to_repo(self, config_repo):
        """disable_plugin calls config_repo.save with 'disabled'."""
        manager = PluginManager(config_repo=config_repo)
        plugin = MockPlugin("test")
        manager.register_plugin(plugin)
        manager.initialize_plugin("test")
        manager.enable_plugin("test")
        config_repo.save.reset_mock()

        manager.disable_plugin("test")

        config_repo.save.assert_called_once_with(
            "test", "disabled", plugin._config, version="1.0.0"
        )

    def test_load_persisted_state_enables_plugins(self, config_repo):
        """load_persisted_state enables plugins that are 'enabled' in store."""
        config_repo.get_enabled.return_value = [
            PluginConfigEntry(plugin_name="test", status="enabled")
        ]

        manager = PluginManager(config_repo=config_repo)
        plugin = MockPlugin("test")
        manager.register_plugin(plugin)
        manager.initialize_plugin("test")

        manager.load_persisted_state()

        assert plugin.status == PluginStatus.ENABLED

    def test_load_persisted_state_skips_unknown_plugins(self, config_repo):
        """load_persisted_state skips plugins not in registry."""
        config_repo.get_enabled.return_value = [
            PluginConfigEntry(plugin_name="unknown", status="enabled")
        ]

        manager = PluginManager(config_repo=config_repo)
        # No plugins registered

        # Should not raise
        manager.load_persisted_state()

    def test_works_without_config_repo(self):
        """PluginManager works without config_repo (backward compatible)."""
        manager = PluginManager()  # No config_repo
        plugin = MockPlugin("test")
        manager.register_plugin(plugin)
        manager.initialize_plugin("test")
        manager.enable_plugin("test")

        assert plugin.status == PluginStatus.ENABLED

        manager.disable_plugin("test")
        assert plugin.status == PluginStatus.DISABLED

        # load_persisted_state is a no-op
        manager.load_persisted_state()

    def test_round_trip_with_mock_store(self):
        """Full round-trip: enable, disable, load_persisted_state."""
        store = MockConfigStore()
        manager = PluginManager(config_repo=store)

        plugin = MockPlugin("test")
        manager.register_plugin(plugin)
        manager.initialize_plugin("test")
        manager.enable_plugin("test")

        # New manager loading same store
        manager2 = PluginManager(config_repo=store)
        plugin2 = MockPlugin("test")
        manager2.register_plugin(plugin2)
        manager2.initialize_plugin("test")
        manager2.load_persisted_state()

        assert plugin2.status == PluginStatus.ENABLED
