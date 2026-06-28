"""Tests for version-aware enable + persisted-state gating (S108.1-S108.3)."""
import logging

import pytest

from vbwd.plugins.base import BasePlugin, PluginMetadata, PluginStatus
from vbwd.plugins.config_store import PluginConfigStore, PluginConfigEntry
from vbwd.plugins.errors import PluginDependencyError
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


class InMemoryStore(PluginConfigStore):
    """In-memory store that records a version pin (like the JSON store)."""

    def __init__(self):
        self._rows = {}  # name -> (status, config, version)

    def get_enabled(self):
        return [
            PluginConfigEntry(
                plugin_name=name,
                status="enabled",
                config=config,
                version=version,
            )
            for name, (status, config, version) in self._rows.items()
            if status == "enabled"
        ]

    def save(self, plugin_name, status, config=None, version=None):
        previous = self._rows.get(plugin_name)
        kept_version = (
            version if version is not None else (previous[2] if previous else None)
        )
        kept_config = (
            config if config is not None else (previous[1] if previous else {})
        )
        self._rows[plugin_name] = (status, kept_config, kept_version)

    def get_by_name(self, plugin_name):
        row = self._rows.get(plugin_name)
        if not row:
            return None
        return PluginConfigEntry(
            plugin_name=plugin_name, status=row[0], config=row[1], version=row[2]
        )

    def get_all(self):
        return [self.get_by_name(name) for name in self._rows]

    def get_config(self, plugin_name):
        row = self._rows.get(plugin_name)
        return row[1] if row else {}

    def save_config(self, plugin_name, config):
        self.save(plugin_name, "disabled", config)

    def force_enabled(self, plugin_name, version=None):
        self._rows[plugin_name] = ("enabled", {}, version)


class TestEnableVersionGate:
    """enable_plugin enforces the version range via the resolver."""

    def test_too_old_dependency_raises_plugin_dependency_error(self):
        manager = PluginManager()
        email = VersionedPlugin("email", version="26.6")
        booking = VersionedPlugin("booking", dependencies=["email>=26.7"])
        for plugin in (email, booking):
            manager.register_plugin(plugin)
            manager.initialize_plugin(plugin.metadata.name)
        manager.enable_plugin("email")

        with pytest.raises(PluginDependencyError) as excinfo:
            manager.enable_plugin("booking")
        assert isinstance(excinfo.value, ValueError)
        assert "email>=26.7" in str(excinfo.value)

    def test_satisfied_dependency_enables(self):
        manager = PluginManager()
        email = VersionedPlugin("email", version="26.7")
        booking = VersionedPlugin("booking", dependencies=["email>=26.7"])
        for plugin in (email, booking):
            manager.register_plugin(plugin)
            manager.initialize_plugin(plugin.metadata.name)
        manager.enable_plugin("email")
        manager.enable_plugin("booking")

        assert booking.status == PluginStatus.ENABLED


class TestLoadPersistedStateGate:
    """load_persisted_state topo-orders and runs the same gate."""

    def test_dependent_before_dependency_both_enable(self):
        store = InMemoryStore()
        # Persisted in the WRONG order: dependent before its dependency.
        store.force_enabled("booking", version="26.6")
        store.force_enabled("email", version="26.6")
        # Re-order dict so booking is iterated first.
        store._rows = {
            "booking": ("enabled", {}, "26.6"),
            "email": ("enabled", {}, "26.6"),
        }

        manager = PluginManager(config_repo=store)
        email = VersionedPlugin("email", version="26.6")
        booking = VersionedPlugin("booking", dependencies=["email"])
        for plugin in (booking, email):
            manager.register_plugin(plugin)
            manager.initialize_plugin(plugin.metadata.name)

        manager.load_persisted_state()

        assert email.status == PluginStatus.ENABLED
        assert booking.status == PluginStatus.ENABLED

    def test_too_old_dependency_skips_dependent_keeps_dependency(self, caplog):
        store = InMemoryStore()
        store._rows = {
            "email": ("enabled", {}, "26.6"),
            "booking": ("enabled", {}, "26.6"),
        }

        manager = PluginManager(config_repo=store)
        email = VersionedPlugin("email", version="26.6")
        booking = VersionedPlugin("booking", dependencies=["email>=26.7"])
        for plugin in (email, booking):
            manager.register_plugin(plugin)
            manager.initialize_plugin(plugin.metadata.name)

        with caplog.at_level(logging.WARNING):
            manager.load_persisted_state()

        assert email.status == PluginStatus.ENABLED
        assert booking.status != PluginStatus.ENABLED
        assert any("booking" in record.message for record in caplog.records)


class TestVersionDriftWarning:
    """The manager warns when the manifest pin != loaded code version."""

    def test_drift_logs_warning(self, caplog):
        store = InMemoryStore()
        # Manifest pins 26.5 but the loaded code is 26.6.
        store._rows = {"email": ("enabled", {}, "26.5")}

        manager = PluginManager(config_repo=store)
        email = VersionedPlugin("email", version="26.6")
        manager.register_plugin(email)
        manager.initialize_plugin("email")

        with caplog.at_level(logging.WARNING):
            manager.load_persisted_state()

        assert any(
            "manifest pins version 26.5" in record.message for record in caplog.records
        )

    def test_no_drift_no_warning(self, caplog):
        store = InMemoryStore()
        store._rows = {"email": ("enabled", {}, "26.6")}

        manager = PluginManager(config_repo=store)
        email = VersionedPlugin("email", version="26.6")
        manager.register_plugin(email)
        manager.initialize_plugin("email")

        with caplog.at_level(logging.WARNING):
            manager.load_persisted_state()

        assert not any("manifest pins" in record.message for record in caplog.records)
