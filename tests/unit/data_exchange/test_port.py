"""Unit tests for the EntityExchanger port + its permission-name defaults."""
import pytest

from vbwd.services.data_exchange.port import (
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)

from .fakes import FakeExportOnlyExchanger


def test_default_permission_names_derive_from_entity_key():
    exchanger = FakeExportOnlyExchanger()
    assert exchanger.export_permission == "fake_reports.export"
    assert exchanger.import_permission == "fake_reports.import"
    assert exchanger.pii_export_permission == "fake_reports.export.pii"


def test_export_only_exchanger_raises_unsupported_on_import():
    """Liskov: a subtype that cannot import raises rather than faking success."""
    exchanger = FakeExportOnlyExchanger()
    with pytest.raises(UnsupportedOperationError):
        exchanger.import_({"fake_reports": []}, mode="upsert", dry_run=False)


def test_export_selector_defaults_are_empty():
    selector = ExportSelector()
    assert selector.ids is None
    assert selector.filters is None
    assert selector.all is False


def test_export_selector_carries_ids_and_filters():
    selector = ExportSelector(ids=["a", "b"], filters={"x": 1}, all=True)
    assert selector.ids == ["a", "b"]
    assert selector.filters == {"x": 1}
    assert selector.all is True


def test_envelope_holds_entity_key_and_rows():
    envelope = Envelope(entity_key="fake_reports", rows=[{"code": "r1"}])
    assert envelope.entity_key == "fake_reports"
    assert envelope.rows == [{"code": "r1"}]


def test_import_result_defaults_to_zero_counts():
    result = ImportResult(entity="x", mode="upsert", dry_run=True)
    assert result.created == 0
    assert result.updated == 0
    assert result.skipped == 0
    assert result.errors == []
