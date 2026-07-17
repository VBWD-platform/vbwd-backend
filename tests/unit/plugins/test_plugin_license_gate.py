"""S137.1 — licence-gated plugin activation.

The point of this gate: a plugin that declares ``requires_license`` must NOT
activate without a covering licence, and — critically — that must hold
*regardless of* ``LICENSE_REQUIRED``. The route-level ``@requires_license``
decorator is inert when that flag is false (an env var defaulting to false), so
honouring the flag here would mean a paid plugin unlocks by simply not setting
an env var. These tests pin that down.
"""
from types import SimpleNamespace

import pytest

from vbwd.plugins.base import BasePlugin, PluginMetadata, PluginStatus
from vbwd.plugins.errors import PluginLicenseError
from vbwd.plugins.manager import PluginManager


class _FakeConfigRepo:
    """Minimal config-store double reporting the given plugins as enabled."""

    def __init__(self, *names):
        self._names = names

    def get_enabled(self):
        return [
            SimpleNamespace(plugin_name=name, config={}, version=None)
            for name in self._names
        ]

    def save(self, *args, **kwargs):
        pass


class _FakeContext:
    """Duck-typed licence context: covers exactly the given scopes."""

    def __init__(self, *covered):
        self._covered = set(covered)

    def has_feature(self, feature):
        return "*" in self._covered or feature in self._covered


class _FreePlugin(BasePlugin):
    @property
    def metadata(self):
        return PluginMetadata(
            name="free_demo", version="1.0.0", author="t", description="free"
        )


class _PaidPlugin(BasePlugin):
    @property
    def metadata(self):
        return PluginMetadata(
            name="paid_demo", version="1.0.0", author="t", description="paid"
        )

    @property
    def requires_license(self):
        return True

    @property
    def licensed_features(self):
        return ("paid_demo",)


class _PaidNoFeatures(BasePlugin):
    """Misconfigured: claims to be paid but declares no feature."""

    @property
    def metadata(self):
        return PluginMetadata(
            name="paid_broken", version="1.0.0", author="t", description="broken"
        )

    @property
    def requires_license(self):
        return True


def _manager(plugin, context=None):
    manager = PluginManager(license_context=context)
    manager.register_plugin(plugin)
    # A plugin must be INITIALIZED before it can be enabled.
    manager.initialize_plugin(plugin.metadata.name, {})
    return manager


def test_free_plugin_enables_without_any_licence():
    """Default (requires_license False) — CE plugins are untouched."""
    manager = _manager(_FreePlugin(), context=None)
    manager.enable_plugin("free_demo")
    assert manager.get_plugin("free_demo").status == PluginStatus.ENABLED


def test_paid_plugin_enables_when_licence_covers_its_feature():
    manager = _manager(_PaidPlugin(), context=_FakeContext("paid_demo"))
    manager.enable_plugin("paid_demo")
    assert manager.get_plugin("paid_demo").status == PluginStatus.ENABLED


def test_paid_plugin_enables_under_wildcard_platform_key():
    manager = _manager(_PaidPlugin(), context=_FakeContext("*"))
    manager.enable_plugin("paid_demo")
    assert manager.get_plugin("paid_demo").status == PluginStatus.ENABLED


def test_paid_plugin_blocked_without_licence_context():
    """Fail closed: no licence at all => no activation."""
    manager = _manager(_PaidPlugin(), context=None)
    with pytest.raises(PluginLicenseError):
        manager.enable_plugin("paid_demo")
    assert manager.get_plugin("paid_demo").status != PluginStatus.ENABLED


def test_paid_plugin_blocked_when_licence_covers_another_feature():
    manager = _manager(_PaidPlugin(), context=_FakeContext("something_else"))
    with pytest.raises(PluginLicenseError):
        manager.enable_plugin("paid_demo")
    assert manager.get_plugin("paid_demo").status != PluginStatus.ENABLED


def test_paid_plugin_declaring_no_feature_fails_closed():
    manager = _manager(_PaidNoFeatures(), context=_FakeContext("*"))
    with pytest.raises(PluginLicenseError):
        manager.enable_plugin("paid_broken")


def test_licence_error_is_a_valueerror_so_existing_callers_skip_cleanly():
    """Liskov: app.py's ``except ValueError`` around enable keeps working."""
    manager = _manager(_PaidPlugin(), context=None)
    with pytest.raises(ValueError):
        manager.enable_plugin("paid_demo")


def test_flipping_license_required_off_does_NOT_unlock_a_paid_plugin():
    """The anti-regression test this whole sprint exists for.

    ``LICENSE_REQUIRED`` is an env-var-backed flag defaulting to false. The
    activation gate must never consult it — otherwise "just don't set it"
    unlocks every paid plugin, which is the exact hole S137 closes.
    """
    manager = _manager(_PaidPlugin(), context=None)
    # Simulate a config where enforcement is explicitly OFF (the CE default).
    manager._license_context = None
    with pytest.raises(PluginLicenseError):
        manager.enable_plugin("paid_demo")
    assert manager.get_plugin("paid_demo").status != PluginStatus.ENABLED


def _persisted_manager(plugin, context=None):
    manager = PluginManager(
        license_context=context,
        config_repo=_FakeConfigRepo(plugin.metadata.name),
    )
    manager.register_plugin(plugin)
    manager.initialize_plugin(plugin.metadata.name, {})
    return manager


def test_persisted_state_boot_path_also_gates_a_paid_plugin():
    """Regression: the REAL boot path must gate too.

    ``load_persisted_state`` calls ``plugin.enable()`` directly instead of
    going through ``enable_plugin``, so it bypassed the licence gate: a
    persisted ``"enabled": true`` in plugins.json activated a paid plugin with
    no licence at all. The gate looked correct and did nothing at boot — this
    pins it.
    """
    plugin = _PaidPlugin()
    manager = _persisted_manager(plugin, context=None)
    manager.load_persisted_state()
    assert plugin.status != PluginStatus.ENABLED


def test_persisted_state_boot_path_enables_a_covered_paid_plugin():
    plugin = _PaidPlugin()
    manager = _persisted_manager(
        plugin, context=_FakeContext("marketplace", "paid_demo")
    )
    manager.load_persisted_state()
    assert plugin.status == PluginStatus.ENABLED


def test_persisted_state_boot_path_leaves_free_plugins_alone():
    plugin = _FreePlugin()
    manager = _persisted_manager(plugin, context=None)
    manager.load_persisted_state()
    assert plugin.status == PluginStatus.ENABLED
