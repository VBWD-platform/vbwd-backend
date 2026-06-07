"""Unit tests for the generic BaseModelExchanger (no real model)."""
import pytest

from vbwd.services.data_exchange.base_model_exchanger import (
    BaseModelExchanger,
    RowCapExceededError,
)
from vbwd.services.data_exchange.port import ExportSelector

from .fakes import FakeRecord, FakeRepository, FakeSession


def make_exchanger(rows=None, *, supported_formats=frozenset({"json", "csv"})):
    repo = FakeRepository(rows)
    session = FakeSession()
    exchanger = BaseModelExchanger(
        entity_key="widgets",
        label="Widgets",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=repo,
        session=session,
        public_fields=["code", "label", "owner_email"],
        secret_fields=frozenset({"secret"}),
        pii_fields=frozenset({"owner_email"}),
        supported_formats=supported_formats,
    )
    return exchanger, repo, session


def sample_rows():
    return [
        FakeRecord("a", "Alpha", "topsecret-a", "alice@example.com"),
        FakeRecord("b", "Beta", "topsecret-b", "bob@example.com"),
    ]


# ── export ───────────────────────────────────────────────────────────────


def test_export_strips_uuid_and_secret_fields():
    exchanger, _repo, _session = make_exchanger(sample_rows())
    envelope = exchanger.export(ExportSelector(all=True), include_pii=True)
    first = envelope.rows[0]
    assert "id" not in first
    assert "secret" not in first
    assert first["code"] == "a"
    assert first["label"] == "Alpha"


def test_export_redacts_pii_without_permission():
    exchanger, _repo, _session = make_exchanger(sample_rows())
    envelope = exchanger.export(ExportSelector(all=True), include_pii=False)
    assert envelope.rows[0]["owner_email"] is None


def test_export_includes_pii_when_permitted():
    exchanger, _repo, _session = make_exchanger(sample_rows())
    envelope = exchanger.export(ExportSelector(all=True), include_pii=True)
    assert envelope.rows[0]["owner_email"] == "alice@example.com"


def test_export_selector_by_ids_filters_rows():
    exchanger, _repo, _session = make_exchanger(sample_rows())
    envelope = exchanger.export(ExportSelector(ids=["b"]), include_pii=True)
    assert [r["code"] for r in envelope.rows] == ["b"]


def test_export_over_row_cap_raises():
    rows = [FakeRecord(str(n), "L", "s", "e@x") for n in range(5)]
    repo = FakeRepository(rows)
    session = FakeSession()
    exchanger = BaseModelExchanger(
        entity_key="widgets",
        label="Widgets",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=repo,
        session=session,
        public_fields=["code"],
        row_cap=2,
    )
    with pytest.raises(RowCapExceededError):
        exchanger.export(ExportSelector(all=True), include_pii=True)


# ── import ───────────────────────────────────────────────────────────────


def test_import_upsert_creates_and_updates():
    exchanger, repo, session = make_exchanger(sample_rows())
    payload = {
        "vbwd_export": "widgets",
        "version": 1,
        "widgets": [
            {"code": "a", "label": "Alpha v2", "owner_email": "alice@example.com"},
            {"code": "c", "label": "Gamma", "owner_email": "carol@example.com"},
        ],
    }
    result = exchanger.import_(payload, mode="upsert", dry_run=False)
    assert result.created == 1
    assert result.updated == 1
    assert session.committed is True
    assert repo.find_by_natural_key("a").label == "Alpha v2"
    assert repo.find_by_natural_key("c") is not None


def test_import_replace_all_drops_then_imports():
    exchanger, repo, session = make_exchanger(sample_rows())
    payload = {
        "vbwd_export": "widgets",
        "version": 1,
        "widgets": [{"code": "z", "label": "Zeta", "owner_email": "z@x"}],
    }
    result = exchanger.import_(payload, mode="replace_all", dry_run=False)
    assert result.created == 1
    codes = sorted(r.code for r in repo.find_all())
    assert codes == ["z"]


def test_dry_run_writes_nothing_and_rolls_back():
    exchanger, repo, session = make_exchanger(sample_rows())
    payload = {
        "vbwd_export": "widgets",
        "version": 1,
        "widgets": [
            {"code": "a", "label": "Alpha v2", "owner_email": "a@x"},
            {"code": "new", "label": "New", "owner_email": "n@x"},
        ],
    }
    before = {r.code: r.label for r in repo.find_all()}
    result = exchanger.import_(payload, mode="upsert", dry_run=True)
    assert result.created == 1
    assert result.updated == 1
    assert session.committed is False
    assert session.rolled_back is True
    after = {r.code: r.label for r in repo.find_all()}
    assert after == before  # nothing actually written


def test_import_supports_default_permissions():
    exchanger, _repo, _session = make_exchanger(sample_rows())
    assert exchanger.export_permission == "widgets.export"
    assert exchanger.import_permission == "widgets.import"
    assert exchanger.pii_export_permission == "widgets.export.pii"
