"""Tests for analytics plugin lifecycle and functionality."""
from src.plugins.base import BasePlugin, PluginStatus
from src.plugins.manager import PluginManager
from plugins.analytics import AnalyticsPlugin


class TestAnalyticsPluginMetadata:
    def test_has_correct_name(self):
        plugin = AnalyticsPlugin()
        assert plugin.metadata.name == "analytics"

    def test_has_correct_version(self):
        plugin = AnalyticsPlugin()
        assert plugin.metadata.version == "1.0.0"

    def test_has_correct_author(self):
        plugin = AnalyticsPlugin()
        assert plugin.metadata.author == "VBWD Team"

    def test_has_no_dependencies(self):
        plugin = AnalyticsPlugin()
        assert plugin.metadata.dependencies == []


class TestAnalyticsPluginInheritance:
    def test_extends_base_plugin(self):
        plugin = AnalyticsPlugin()
        assert isinstance(plugin, BasePlugin)


class TestAnalyticsPluginLifecycle:
    def test_initial_status_is_discovered(self):
        plugin = AnalyticsPlugin()
        assert plugin.status == PluginStatus.DISCOVERED

    def test_initialize_sets_initialized(self):
        plugin = AnalyticsPlugin()
        plugin.initialize()
        assert plugin.status == PluginStatus.INITIALIZED

    def test_enable_sets_enabled(self):
        plugin = AnalyticsPlugin()
        plugin.initialize()
        plugin.enable()
        assert plugin.status == PluginStatus.ENABLED

    def test_disable_sets_disabled(self):
        plugin = AnalyticsPlugin()
        plugin.initialize()
        plugin.enable()
        plugin.disable()
        assert plugin.status == PluginStatus.DISABLED

    def test_on_enable_sets_active_flag(self):
        plugin = AnalyticsPlugin()
        plugin.initialize()
        plugin.enable()
        assert plugin._active is True

    def test_on_disable_clears_active_flag(self):
        plugin = AnalyticsPlugin()
        plugin.initialize()
        plugin.enable()
        plugin.disable()
        assert plugin._active is False


class TestAnalyticsPluginFunctionality:
    def test_get_active_sessions_returns_dict(self):
        plugin = AnalyticsPlugin()
        plugin.initialize()
        plugin.enable()
        result = plugin.get_active_sessions()
        assert isinstance(result, dict)
        assert "count" in result
        assert "source" in result
        assert result["source"] == "plugin"
        assert isinstance(result["count"], int)

    def test_get_active_sessions_uses_injected_count_fn(self):
        plugin = AnalyticsPlugin()
        plugin.initialize({"session_count_fn": lambda: 42})
        plugin.enable()
        result = plugin.get_active_sessions()
        assert result["count"] == 42

    def test_get_active_sessions_default_count_is_zero(self):
        plugin = AnalyticsPlugin()
        plugin.initialize()
        plugin.enable()
        result = plugin.get_active_sessions()
        assert result["count"] == 0

    def test_handles_count_fn_exception(self):
        def bad_fn():
            raise RuntimeError("fail")

        plugin = AnalyticsPlugin()
        plugin.initialize({"session_count_fn": bad_fn})
        plugin.enable()
        result = plugin.get_active_sessions()
        assert result["count"] == 0


class TestAnalyticsPluginWithManager:
    def test_registers_with_manager(self):
        manager = PluginManager()
        plugin = AnalyticsPlugin()
        manager.register_plugin(plugin)
        assert manager.get_plugin("analytics") is plugin

    def test_full_lifecycle_via_manager(self):
        manager = PluginManager()
        plugin = AnalyticsPlugin()
        manager.register_plugin(plugin)
        manager.initialize_plugin("analytics")
        manager.enable_plugin("analytics")
        assert plugin.status == PluginStatus.ENABLED
        manager.disable_plugin("analytics")
        assert plugin.status == PluginStatus.DISABLED

    def test_provides_blueprint(self):
        plugin = AnalyticsPlugin()
        bp = plugin.get_blueprint()
        assert bp is not None
        assert bp.name == "analytics_plugin"

    def test_provides_url_prefix(self):
        plugin = AnalyticsPlugin()
        assert plugin.get_url_prefix() == "/api/v1/plugins/analytics"
