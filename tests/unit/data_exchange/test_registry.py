"""Unit tests for DataExchangeRegistry — register/get/all/clear + manifest_for."""
import pytest

from vbwd.services.data_exchange.registry import DataExchangeRegistry

from .fakes import FakeExportOnlyExchanger, make_user


class _SettingsExchanger(FakeExportOnlyExchanger):
    entity_key = "fake_settings_thing"
    label = "Fake Settings Thing"
    cluster = "settings"
    supports_import = True
    supported_formats = frozenset({"json", "csv"})

    def import_(self, payload, *, mode, dry_run):  # pragma: no cover - not exercised
        from vbwd.services.data_exchange.port import ImportResult

        return ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)


class _SalesImportableExchanger(FakeExportOnlyExchanger):
    entity_key = "fake_sales_thing"
    label = "Fake Sales Thing"
    cluster = "sales"
    supports_import = True
    pii_fields = frozenset({"owner_email"})

    def import_(self, payload, *, mode, dry_run):  # pragma: no cover - not exercised
        from vbwd.services.data_exchange.port import ImportResult

        return ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)


@pytest.fixture
def registry():
    reg = DataExchangeRegistry()
    yield reg
    reg.clear()


def test_register_get_all_clear(registry):
    exchanger = FakeExportOnlyExchanger()
    registry.register(exchanger)
    assert registry.get("fake_reports") is exchanger
    assert exchanger in registry.all()
    registry.clear()
    assert registry.all() == []
    assert registry.get("fake_reports") is None


def test_manifest_superadmin_sees_all_with_all_flags(registry):
    registry.register(_SalesImportableExchanger())
    superadmin = make_user(superadmin=True)

    manifest = registry.manifest_for(superadmin)

    assert len(manifest) == 1
    item = manifest[0]
    assert item["entity_key"] == "fake_sales_thing"
    assert item["cluster"] == "sales"
    assert item["can_export"] is True
    assert item["can_import"] is True
    assert item["can_export_pii"] is True
    assert item["supported_formats"] == ["json"]


def test_manifest_scoped_sales_user_sees_only_granted_flags(registry):
    registry.register(_SalesImportableExchanger())
    user = make_user(permissions=["fake_sales_thing.export"])

    manifest = registry.manifest_for(user)

    assert len(manifest) == 1
    item = manifest[0]
    assert item["can_export"] is True
    assert item["can_import"] is False
    assert item["can_export_pii"] is False


def test_manifest_user_with_no_perms_drops_entity(registry):
    registry.register(_SalesImportableExchanger())
    user = make_user(permissions=[])

    manifest = registry.manifest_for(user)

    assert manifest == []


def test_manifest_settings_cluster_gates_on_settings_perms(registry):
    registry.register(_SettingsExchanger())
    viewer = make_user(permissions=["settings.view"])

    manifest = registry.manifest_for(viewer)

    assert len(manifest) == 1
    item = manifest[0]
    assert item["cluster"] == "settings"
    assert item["can_export"] is True
    assert item["can_import"] is False  # needs settings.manage


def test_manifest_settings_manage_enables_import(registry):
    registry.register(_SettingsExchanger())
    manager = make_user(permissions=["settings.view", "settings.manage"])

    item = registry.manifest_for(manager)[0]
    assert item["can_export"] is True
    assert item["can_import"] is True


def test_manifest_config_allow_list_filters_entities(registry):
    registry.register(_SalesImportableExchanger())
    registry.register(_SettingsExchanger())
    superadmin = make_user(superadmin=True)

    manifest = registry.manifest_for(
        superadmin, enabled_entities=["fake_settings_thing"]
    )

    keys = [item["entity_key"] for item in manifest]
    assert keys == ["fake_settings_thing"]


def test_manifest_default_allow_list_is_all(registry):
    registry.register(_SalesImportableExchanger())
    registry.register(_SettingsExchanger())
    superadmin = make_user(superadmin=True)

    manifest = registry.manifest_for(superadmin, enabled_entities=None)
    assert len(manifest) == 2
