"""The permission catalog includes data-exchange perms grouped by cluster."""
import pytest

from vbwd.services.data_exchange.registry import data_exchange_registry
from vbwd.services.permission_catalog import collect_permission_catalog

from .fakes import FakeExportOnlyExchanger


class _ImportableSalesExchanger(FakeExportOnlyExchanger):
    entity_key = "fake_orders"
    label = "Fake Orders"
    cluster = "sales"
    supports_import = True
    pii_fields = frozenset({"owner_email"})

    def import_(self, payload, *, mode, dry_run):  # pragma: no cover
        from vbwd.services.data_exchange.port import ImportResult

        return ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)


class _SettingsExchanger(FakeExportOnlyExchanger):
    entity_key = "fake_palette"
    label = "Fake Palette"
    cluster = "settings"
    supports_import = True

    def import_(self, payload, *, mode, dry_run):  # pragma: no cover
        from vbwd.services.data_exchange.port import ImportResult

        return ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)


@pytest.fixture(autouse=True)
def _clean_registry():
    data_exchange_registry.clear()
    yield
    data_exchange_registry.clear()


def test_catalog_contributes_sales_entity_perms(app):
    data_exchange_registry.register(_ImportableSalesExchanger())

    with app.app_context():
        catalog = collect_permission_catalog()

    keys = [entry["key"] for entry in catalog.get("data_exchange", [])]
    assert "fake_orders.export" in keys
    assert "fake_orders.import" in keys
    assert "fake_orders.export.pii" in keys


def test_settings_cluster_contributes_no_new_perms(app):
    data_exchange_registry.register(_SettingsExchanger())

    with app.app_context():
        catalog = collect_permission_catalog()

    keys = [entry["key"] for entry in catalog.get("data_exchange", [])]
    assert keys == []  # settings cluster reuses settings.view / settings.manage


def test_catalog_groups_perms_by_cluster_label(app):
    data_exchange_registry.register(_ImportableSalesExchanger())

    with app.app_context():
        catalog = collect_permission_catalog()

    groups = {entry["group"] for entry in catalog.get("data_exchange", [])}
    assert groups == {"Data Exchange — Sales"}


def test_export_only_entity_has_no_import_perm(app):
    data_exchange_registry.register(FakeExportOnlyExchanger())  # export only

    with app.app_context():
        catalog = collect_permission_catalog()

    keys = [entry["key"] for entry in catalog.get("data_exchange", [])]
    assert "fake_reports.export" in keys
    assert "fake_reports.import" not in keys
    assert "fake_reports.export.pii" not in keys  # no pii_fields
