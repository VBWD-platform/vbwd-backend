"""S89 Slice 2b — server-side stage-timing collector (load-env-gated).

The collector is inert unless ``VBWD_DATA_EXCHANGE_PROFILE`` is set: with the
flag off a named span adds nothing and ``profiling_enabled()`` is False, so the
export/import response is byte-identical (Liskov: the profile data is purely
additive). With the flag on, spans accumulate and the SQLAlchemy hook attributes
statements to the active operation. The DB-time path (query_count / db_seconds)
needs a real engine and is asserted in the integration suite; here we cover the
flag gate, the named-span accounting, the verb split, and the header rendering.
"""
import time

import pytest

from vbwd.services.data_exchange import profiling
from vbwd.services.data_exchange.profiling import (
    PROFILE_ENV_VAR,
    SPAN_SERIALISE,
    StageProfile,
)


def test_profiling_disabled_by_default(monkeypatch):
    monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    assert profiling.profiling_enabled() is False


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on"])
def test_profiling_enabled_truthy_values(monkeypatch, truthy):
    monkeypatch.setenv(PROFILE_ENV_VAR, truthy)
    assert profiling.profiling_enabled() is True


@pytest.mark.parametrize("falsy", ["0", "false", "no", "off", ""])
def test_profiling_disabled_falsy_values(monkeypatch, falsy):
    monkeypatch.setenv(PROFILE_ENV_VAR, falsy)
    assert profiling.profiling_enabled() is False


def test_named_span_is_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    with profiling.start_operation() as stage_profile:
        with profiling.span(SPAN_SERIALISE):
            time.sleep(0.005)
    # With the flag off, span() returns the shared no-op (no clock read), so the
    # span records nothing into the profile — the totals stay zero and the route
    # emits no header / no _profile.
    assert profiling.profiling_enabled() is False
    assert stage_profile.spans == {}
    # And the active profile is cleared after the operation.
    assert profiling.active_profile() is None


def test_named_span_accumulates_time_when_active(monkeypatch):
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    with profiling.start_operation() as stage_profile:
        with profiling.span(SPAN_SERIALISE):
            time.sleep(0.01)
    assert stage_profile.spans[SPAN_SERIALISE] > 0


def test_span_outside_operation_is_silent(monkeypatch):
    """A span with no active operation must not crash (no profile to record to)."""
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    with profiling.span(SPAN_SERIALISE):
        time.sleep(0.001)
    assert profiling.active_profile() is None


def test_record_statement_splits_by_verb():
    profile = StageProfile()
    profile.record_statement("SELECT 1", 0.10)
    profile.record_statement("INSERT INTO t VALUES (1)", 0.20)
    profile.record_statement("UPDATE t SET x=1", 0.05)
    profile.record_statement("COMMIT", 0.01)
    assert profile.query_count == 4
    assert profile.db_read_seconds == pytest.approx(0.10)
    assert profile.db_write_seconds == pytest.approx(0.25)
    assert profile.db_commit_seconds == pytest.approx(0.01)
    assert profile.db_seconds == pytest.approx(0.36)


def test_to_dict_exposes_stage_split():
    profile = StageProfile()
    profile.record_statement("SELECT 1", 0.1)
    profile.add_span(SPAN_SERIALISE, 0.02)
    data = profile.to_dict()
    assert data["query_count"] == 1
    assert data["db_seconds"]["read"] == pytest.approx(0.1)
    assert data["serialise_seconds"] == pytest.approx(0.02)


def test_server_timing_header_contains_stages():
    profile = StageProfile()
    profile.record_statement("SELECT 1", 0.1)
    profile.add_span(SPAN_SERIALISE, 0.02)
    header = profile.server_timing_header()
    assert "db_read" in header
    assert "serialise" in header
    assert "queries" in header
