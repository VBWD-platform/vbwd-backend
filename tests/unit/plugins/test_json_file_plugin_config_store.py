"""Tests for JsonFilePluginConfigStore."""
import json
import os
import pytest
from vbwd.plugins.json_config_store import JsonFilePluginConfigStore
from vbwd.plugins.config_store import PluginConfigStore, PluginConfigEntry


class TestJsonFilePluginConfigStore:
    """Test JSON-file-based plugin config store."""

    @pytest.fixture
    def plugins_dir(self, tmp_path):
        """Return a temp directory for plugin JSON files."""
        return str(tmp_path)

    @pytest.fixture
    def store(self, plugins_dir):
        return JsonFilePluginConfigStore(plugins_dir)

    def _write_plugins(self, plugins_dir, plugins):
        with open(os.path.join(plugins_dir, "plugins.json"), "w") as f:
            json.dump({"plugins": plugins}, f)

    def _write_config(self, plugins_dir, config):
        with open(os.path.join(plugins_dir, "config.json"), "w") as f:
            json.dump(config, f)

    def _read_plugins(self, plugins_dir):
        with open(os.path.join(plugins_dir, "plugins.json"), "r") as f:
            return json.load(f)["plugins"]

    def _read_config(self, plugins_dir):
        with open(os.path.join(plugins_dir, "config.json"), "r") as f:
            return json.load(f)

    def test_lsp_compliance(self, store):
        """JsonFilePluginConfigStore is a PluginConfigStore."""
        assert isinstance(store, PluginConfigStore)

    def test_get_enabled_returns_enabled_plugins(self, store, plugins_dir):
        """get_enabled returns only enabled plugins."""
        self._write_plugins(
            plugins_dir,
            {
                "analytics": {"enabled": True, "version": "1.0.0"},
                "demo": {"enabled": False, "version": "1.0.0"},
            },
        )
        self._write_config(plugins_dir, {"analytics": {"key": "val"}})

        result = store.get_enabled()
        assert len(result) == 1
        assert result[0].plugin_name == "analytics"
        assert result[0].status == "enabled"
        assert result[0].config == {"key": "val"}

    def test_save_enables_plugin_updates_json(self, store, plugins_dir):
        """save with status='enabled' sets enabled=True in JSON."""
        self._write_plugins(
            plugins_dir,
            {
                "demo": {"enabled": False, "version": "1.0.0"},
            },
        )
        self._write_config(plugins_dir, {})

        store.save("demo", "enabled")

        plugins = self._read_plugins(plugins_dir)
        assert plugins["demo"]["enabled"] is True

    def test_save_disables_plugin_updates_json(self, store, plugins_dir):
        """save with status='disabled' sets enabled=False in JSON."""
        self._write_plugins(
            plugins_dir,
            {
                "demo": {"enabled": True, "version": "1.0.0"},
            },
        )
        self._write_config(plugins_dir, {})

        store.save("demo", "disabled")

        plugins = self._read_plugins(plugins_dir)
        assert plugins["demo"]["enabled"] is False

    def test_save_creates_new_plugin_entry(self, store, plugins_dir):
        """save creates new entry in plugins.json if plugin doesn't exist."""
        self._write_plugins(plugins_dir, {})
        self._write_config(plugins_dir, {})

        store.save("new-plugin", "enabled", {"setting": True})

        plugins = self._read_plugins(plugins_dir)
        assert "new-plugin" in plugins
        assert plugins["new-plugin"]["enabled"] is True

        config = self._read_config(plugins_dir)
        assert config["new-plugin"] == {"setting": True}

    def test_save_with_config_persists(self, store, plugins_dir):
        """save with config persists config to config.json."""
        self._write_plugins(
            plugins_dir,
            {
                "demo": {"enabled": False, "version": "1.0.0"},
            },
        )
        self._write_config(plugins_dir, {})

        store.save("demo", "enabled", {"greeting": "Hello"})

        config = self._read_config(plugins_dir)
        assert config["demo"] == {"greeting": "Hello"}

    def test_get_by_name_returns_entry(self, store, plugins_dir):
        """get_by_name returns PluginConfigEntry for existing plugin."""
        self._write_plugins(
            plugins_dir,
            {
                "demo": {"enabled": True, "version": "1.0.0"},
            },
        )
        self._write_config(plugins_dir, {"demo": {"key": "val"}})

        result = store.get_by_name("demo")
        assert isinstance(result, PluginConfigEntry)
        assert result.plugin_name == "demo"
        assert result.status == "enabled"
        assert result.config == {"key": "val"}

    def test_get_by_name_returns_none_for_unknown(self, store, plugins_dir):
        """get_by_name returns None for unknown plugin."""
        self._write_plugins(plugins_dir, {})

        result = store.get_by_name("unknown")
        assert result is None

    def test_get_all_returns_all_entries(self, store, plugins_dir):
        """get_all returns all plugins regardless of status."""
        self._write_plugins(
            plugins_dir,
            {
                "analytics": {"enabled": True, "version": "1.0.0"},
                "demo": {"enabled": False, "version": "1.0.0"},
            },
        )
        self._write_config(plugins_dir, {})

        result = store.get_all()
        assert len(result) == 2
        names = [e.plugin_name for e in result]
        assert "analytics" in names
        assert "demo" in names

    def test_get_config_returns_saved_config(self, store, plugins_dir):
        """get_config returns saved config values for a plugin."""
        self._write_config(plugins_dir, {"demo": {"greeting": "Hi"}})

        result = store.get_config("demo")
        assert result == {"greeting": "Hi"}

    def test_get_config_returns_empty_for_unknown(self, store, plugins_dir):
        """get_config returns empty dict for unknown plugin."""
        self._write_config(plugins_dir, {})

        result = store.get_config("unknown")
        assert result == {}

    def test_save_config_persists_to_file(self, store, plugins_dir):
        """save_config persists config to config.json."""
        self._write_config(plugins_dir, {})

        store.save_config("demo", {"greeting": "Hello!"})

        config = self._read_config(plugins_dir)
        assert config["demo"] == {"greeting": "Hello!"}

    def test_save_config_updates_existing(self, store, plugins_dir):
        """save_config updates existing config values."""
        self._write_config(plugins_dir, {"demo": {"old": "value"}})

        store.save_config("demo", {"new": "value"})

        config = self._read_config(plugins_dir)
        assert config["demo"] == {"new": "value"}

    def test_handles_missing_plugins_file_gracefully(self, store):
        """Handles missing plugins.json gracefully."""
        result = store.get_enabled()
        assert result == []

    def test_handles_missing_config_file_gracefully(self, store):
        """Handles missing config.json gracefully."""
        result = store.get_config("demo")
        assert result == {}

    def test_handles_missing_directory_on_write(self, tmp_path):
        """Creates directory if it doesn't exist when writing."""
        nested_dir = str(tmp_path / "nested" / "plugins")
        store = JsonFilePluginConfigStore(nested_dir)

        store.save("demo", "enabled")

        assert os.path.exists(os.path.join(nested_dir, "plugins.json"))

    def test_save_writes_passed_version(self, store, plugins_dir):
        """save with a version stamps the passed value (not the 1.0.0 default)."""
        self._write_plugins(
            plugins_dir, {"demo": {"enabled": False, "version": "1.0.0"}}
        )
        self._write_config(plugins_dir, {})

        store.save("demo", "enabled", version="26.7")

        plugins = self._read_plugins(plugins_dir)
        assert plugins["demo"]["version"] == "26.7"

    def test_save_new_entry_stamps_version(self, store, plugins_dir):
        """save creating a new entry stamps the passed version."""
        self._write_plugins(plugins_dir, {})
        self._write_config(plugins_dir, {})

        store.save("new-plugin", "enabled", version="26.6")

        plugins = self._read_plugins(plugins_dir)
        assert plugins["new-plugin"]["version"] == "26.6"

    def test_save_without_version_preserves_existing_pin(self, store, plugins_dir):
        """A status-only save (version omitted) preserves the existing pin."""
        self._write_plugins(
            plugins_dir, {"demo": {"enabled": False, "version": "26.6"}}
        )
        self._write_config(plugins_dir, {})

        store.save("demo", "enabled")

        plugins = self._read_plugins(plugins_dir)
        assert plugins["demo"]["version"] == "26.6"

    def test_entries_expose_version(self, store, plugins_dir):
        """get_by_name / get_enabled surface the persisted version pin."""
        self._write_plugins(plugins_dir, {"demo": {"enabled": True, "version": "26.6"}})
        self._write_config(plugins_dir, {})

        assert store.get_by_name("demo").version == "26.6"
        assert store.get_enabled()[0].version == "26.6"
