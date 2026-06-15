"""S89 Slice 0 — configurable default row cap.

``DEFAULT_ROW_CAP`` (10000) stays the safe default; the per-process default is
overridable via ``VBWD_DATA_EXCHANGE_ROW_CAP`` so the load harness can lift the
guard for a measured run while production (var unset) stays protected. The
override only changes the *source* of the default — an explicit ``row_cap=`` on
the exchanger still wins (Liskov: the default path is behaviour-preserving).
"""
import pytest

from vbwd.services.data_exchange.base_model_exchanger import (
    DEFAULT_ROW_CAP,
    ROW_CAP_ENV_VAR,
    BaseModelExchanger,
    RowCapExceededError,
    resolve_default_row_cap,
)
from vbwd.services.data_exchange.port import ExportSelector

from .fakes import FakeRecord, FakeRepository, FakeSession


def _make_exchanger(row_count: int):
    rows = [FakeRecord(str(n), "L", "s", "e@x") for n in range(row_count)]
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
        # row_cap=None → use the env-resolved default (the slice's contract).
    )
    return exchanger


def test_unset_env_keeps_default_cap(monkeypatch):
    monkeypatch.delenv(ROW_CAP_ENV_VAR, raising=False)
    assert resolve_default_row_cap() == DEFAULT_ROW_CAP


def test_unset_env_rejects_over_ten_thousand(monkeypatch):
    monkeypatch.delenv(ROW_CAP_ENV_VAR, raising=False)
    exchanger = _make_exchanger(DEFAULT_ROW_CAP + 1)
    with pytest.raises(RowCapExceededError):
        exchanger.export(ExportSelector(all=True), include_pii=True)


def test_env_override_lifts_cap(monkeypatch):
    monkeypatch.setenv(ROW_CAP_ENV_VAR, "500000")
    assert resolve_default_row_cap() == 500000
    # 10001 rows now pass (below the lifted cap).
    exchanger = _make_exchanger(DEFAULT_ROW_CAP + 1)
    envelope = exchanger.export(ExportSelector(all=True), include_pii=True)
    assert len(envelope.rows) == DEFAULT_ROW_CAP + 1


def test_env_override_still_enforces_new_cap(monkeypatch):
    monkeypatch.setenv(ROW_CAP_ENV_VAR, "5")
    exchanger = _make_exchanger(6)
    with pytest.raises(RowCapExceededError):
        exchanger.export(ExportSelector(all=True), include_pii=True)


@pytest.mark.parametrize("bad_value", ["0", "-5", "not-a-number", ""])
def test_garbage_or_zero_env_falls_back_to_default(monkeypatch, bad_value):
    monkeypatch.setenv(ROW_CAP_ENV_VAR, bad_value)
    assert resolve_default_row_cap() == DEFAULT_ROW_CAP


def test_explicit_row_cap_overrides_env(monkeypatch):
    """An explicit ``row_cap=`` still wins over the env default (unchanged contract)."""
    monkeypatch.setenv(ROW_CAP_ENV_VAR, "500000")
    rows = [FakeRecord(str(n), "L", "s", "e@x") for n in range(3)]
    exchanger = BaseModelExchanger(
        entity_key="widgets",
        label="Widgets",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=FakeRepository(rows),
        session=FakeSession(),
        public_fields=["code"],
        row_cap=2,
    )
    with pytest.raises(RowCapExceededError):
        exchanger.export(ExportSelector(all=True), include_pii=True)
