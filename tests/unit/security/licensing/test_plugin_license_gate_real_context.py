"""S137.1 licence gate driven through the REAL licensing collaborators.

``tests/unit/plugins/test_plugin_license_gate.py`` pins the gate's rules with a
duck-typed fake context. This suite wires the same ``PluginManager`` gate to a
real ``LicenseStore`` fed with fixture-signed envelopes and a real
``LicenseContext`` (or one built by ``build_license_environment``), so coverage
semantics — scoped, wildcard, grace window, expired — are asserted against the
code the boot path actually runs, not a double.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from vbwd.plugins.base import BasePlugin, PluginMetadata, PluginStatus
from vbwd.plugins.errors import PluginLicenseError
from vbwd.plugins.manager import PluginManager
from vbwd.security.licensing.license_context import LicenseContext
from vbwd.security.licensing.license_store import LicenseStore
from vbwd.security.licensing.loader import build_license_environment
from vbwd.security.licensing.verifier import LicenseVerifier

from .conftest import FIXED_NOW, FIXTURE_INSTANCE_ID, make_license_key, mint_envelope

PAID_FEATURE = "some-paid-feature"
OTHER_FEATURE = "a-different-feature"
GRACE_DAYS = 14
DAYS_EXPIRED_WITHIN_GRACE = 3
DAYS_EXPIRED_PAST_GRACE = 60


class LicensedPlugin(BasePlugin):
    """A plugin that declares itself licence-requiring."""

    def __init__(self):
        super().__init__()
        self.on_enable_calls = 0

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="licensed-plugin",
            version="1.0.0",
            author="Test",
            description="Requires a licence",
        )

    @property
    def requires_license(self) -> bool:
        return True

    @property
    def licensed_features(self) -> tuple:
        return (PAID_FEATURE,)

    def on_enable(self) -> None:
        self.on_enable_calls += 1


@pytest.fixture
def store(tmp_path, signer, fixed_clock):
    verifier = LicenseVerifier(signer, FIXTURE_INSTANCE_ID, fixed_clock)
    return LicenseStore(str(tmp_path), verifier)


def _manager_for(context) -> tuple:
    """A manager wired to ``context`` with a registered, initialized plugin."""
    manager = PluginManager(license_context=context)
    plugin = LicensedPlugin()
    manager.register_plugin(plugin)
    manager.initialize_plugin(plugin.metadata.name)
    return manager, plugin


def _write_key_file(tmp_path, key, signer):
    """Persist an envelope directly (a key may expire while already held)."""
    (tmp_path / f"{key.key_id}.vbwd").write_text(mint_envelope(key, signer))


def _expired_key(days_ago: int):
    return make_license_key(
        scope=(PAID_FEATURE,),
        expires_at=FIXED_NOW - timedelta(days=days_ago),
        grace_days=GRACE_DAYS,
    )


class TestCoveredLicenseActivates:
    """A held, covering key lets the plugin activate normally."""

    def test_scoped_key_covering_the_feature_activates(self, store, signer):
        store.add(mint_envelope(make_license_key(scope=(PAID_FEATURE,)), signer))
        manager, plugin = _manager_for(LicenseContext(store))

        manager.enable_plugin(plugin.metadata.name)

        assert plugin.status == PluginStatus.ENABLED
        assert plugin.on_enable_calls == 1

    def test_platform_wildcard_key_covers_it(self, store, signer):
        store.add(mint_envelope(make_license_key(scope=("*",)), signer))
        manager, plugin = _manager_for(LicenseContext(store))

        manager.enable_plugin(plugin.metadata.name)

        assert plugin.status == PluginStatus.ENABLED

    def test_key_inside_the_grace_window_still_covers(self, store, signer, tmp_path):
        _write_key_file(tmp_path, _expired_key(DAYS_EXPIRED_WITHIN_GRACE), signer)
        manager, plugin = _manager_for(LicenseContext(store))

        manager.enable_plugin(plugin.metadata.name)

        assert plugin.status == PluginStatus.ENABLED


class TestUncoveredLicenseBlocks:
    """A held key that does not cover the plugin ⇒ it does not activate."""

    def test_key_covering_a_different_feature_does_not_activate(self, store, signer):
        store.add(mint_envelope(make_license_key(scope=(OTHER_FEATURE,)), signer))
        manager, plugin = _manager_for(LicenseContext(store))

        with pytest.raises(PluginLicenseError):
            manager.enable_plugin(plugin.metadata.name)

        assert plugin.status != PluginStatus.ENABLED
        assert plugin.on_enable_calls == 0

    def test_expired_key_past_grace_does_not_activate(self, store, signer, tmp_path):
        _write_key_file(tmp_path, _expired_key(DAYS_EXPIRED_PAST_GRACE), signer)
        manager, plugin = _manager_for(LicenseContext(store))

        with pytest.raises(PluginLicenseError):
            manager.enable_plugin(plugin.metadata.name)

        assert plugin.status != PluginStatus.ENABLED


def test_boot_built_environment_with_a_covering_key_activates(
    tmp_path, signer, fixed_clock
):
    """``LICENSE_REQUIRED`` false (the CE flag) never punishes a paying customer."""
    _write_key_file(tmp_path, make_license_key(scope=(PAID_FEATURE,)), signer)
    environment = build_license_environment(
        {
            "LICENSE_REQUIRED": False,
            "LICENSE_KEYS_DIR": str(tmp_path),
            "LICENSE_INSTANCE_ID": FIXTURE_INSTANCE_ID,
            "LICENSE_SIGNATURE_VERIFIER": signer,
        },
        clock=fixed_clock,
    )
    manager, plugin = _manager_for(environment.context)

    manager.enable_plugin(plugin.metadata.name)

    assert plugin.status == PluginStatus.ENABLED


class FreePlugin(BasePlugin):
    """A plugin that declares no licence requirement (the CE default)."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="free-plugin",
            version="1.0.0",
            author="Test",
            description="Needs no licence",
        )


class _PersistedEnabledStore:
    """Config-store double reporting the given plugins as persisted-enabled."""

    def __init__(self, *plugin_names):
        self._plugin_names = plugin_names

    def get_enabled(self):
        return [
            SimpleNamespace(plugin_name=name, config={}, version=None)
            for name in self._plugin_names
        ]


def _keyless_context(tmp_path):
    """The context a keyless install boots with (no public key, no keys)."""
    return build_license_environment(
        {"LICENSE_REQUIRED": False, "LICENSE_KEYS_DIR": str(tmp_path / "keys")}
    ).context


class TestKeylessInstall:
    """Closing the keyless gap (2026-10-06): no licence material ⇒ not granted."""

    def test_admin_enable_of_a_licensed_plugin_is_refused(self, tmp_path):
        manager, plugin = _manager_for(_keyless_context(tmp_path))

        with pytest.raises(PluginLicenseError):
            manager.enable_plugin(plugin.metadata.name)

        assert plugin.status != PluginStatus.ENABLED
        assert plugin.on_enable_calls == 0

    def test_boot_leaves_licensed_plugin_disabled_and_free_plugin_enabled(
        self, tmp_path
    ):
        licensed_plugin, free_plugin = LicensedPlugin(), FreePlugin()
        manager = PluginManager(
            license_context=_keyless_context(tmp_path),
            config_repo=_PersistedEnabledStore(
                licensed_plugin.metadata.name, free_plugin.metadata.name
            ),
        )
        for plugin in (licensed_plugin, free_plugin):
            manager.register_plugin(plugin)
            manager.initialize_plugin(plugin.metadata.name)

        manager.load_persisted_state()

        assert licensed_plugin.status != PluginStatus.ENABLED
        assert licensed_plugin.on_enable_calls == 0
        assert free_plugin.status == PluginStatus.ENABLED
