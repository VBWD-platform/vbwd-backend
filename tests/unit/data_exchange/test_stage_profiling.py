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


# ── §2.2 attribution enrichment (S89 Slice 2b follow-up) ──────────────────────

# The field names the harness reads verbatim from the ``_profile`` dict
# (``vbwd-platform/tests/load/data_exchange_bench.py`` → ``assemble_result`` and
# ``data_exchange_runners.py`` → ``_peak_rss_mb_from_profile_or_zero``). These
# MUST match byte-for-byte or the enrichment never reaches the bench.
_HARNESS_ATTRIBUTION_KEYS = {
    "peak_rss_mb",
    "gc_collections",
    "gc_pause_seconds",
    "longest_txn_seconds",
    "longest_lock_wait_seconds",
    "app_cpu_pct",
    "db_cpu_pct",
    "table_bytes",
    "index_bytes",
}


def test_to_dict_omits_attribution_keys_when_flag_off(monkeypatch):
    """Liskov: with the flag off ``to_dict()`` is byte-identical to the original
    contract — none of the §2.2 attribution keys are present."""
    monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    profile = StageProfile()
    profile.record_statement("SELECT 1", 0.1)
    data = profile.to_dict()
    assert set(data) == {
        "query_count",
        "db_seconds",
        "serialise_seconds",
        "deserialise_seconds",
    }
    for key in _HARNESS_ATTRIBUTION_KEYS:
        assert key not in data


def test_to_dict_exposes_attribution_keys_when_flag_on(monkeypatch):
    """With the flag on, every §2.2 attribution key the harness reads is present
    (verbatim names) so the enrichment flows through with no harness change."""
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    profile = StageProfile()
    profile.peak_rss_mb = 12.5
    profile.gc_collections = 3
    profile.gc_pause_seconds = 0.004
    profile.table_bytes = 4096
    profile.index_bytes = 2048
    data = profile.to_dict()
    for key in _HARNESS_ATTRIBUTION_KEYS:
        assert key in data, f"missing harness key {key!r}"
    assert data["peak_rss_mb"] == pytest.approx(12.5)
    assert data["gc_collections"] == 3
    assert data["table_bytes"] == 4096
    assert data["index_bytes"] == 2048


def test_attribution_defaults_are_best_effort_none(monkeypatch):
    """A profile with no capture run yet exposes the keys as best-effort None / 0
    — values are never invented; only an operation span populates them."""
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    profile = StageProfile()
    data = profile.to_dict()
    # gc_pause_seconds is an additive float counter (0.0 baseline, never None).
    assert isinstance(data["gc_pause_seconds"], float)
    # Everything else is best-effort: None until an operation span captures it.
    assert data["peak_rss_mb"] is None
    assert data["gc_collections"] is None
    assert data["longest_txn_seconds"] is None
    assert data["longest_lock_wait_seconds"] is None
    assert data["app_cpu_pct"] is None
    # db_cpu_pct is documented best-effort-None on this env (no cheap source).
    assert data["db_cpu_pct"] is None
    assert data["table_bytes"] is None
    assert data["index_bytes"] is None


def test_start_operation_captures_rss_and_gc_when_on(monkeypatch):
    """Flag on: an operation span samples peak RSS (> 0 MB) and a GC collection
    count (int ≥ 0) over the op — stdlib only, no new dependency."""
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    with profiling.start_operation() as stage_profile:
        # Churn some objects so RSS/GC have something to observe.
        _churn = [object() for _ in range(10000)]
        del _churn
    assert stage_profile.peak_rss_mb is not None
    assert stage_profile.peak_rss_mb > 0
    assert isinstance(stage_profile.gc_collections, int)
    assert stage_profile.gc_collections >= 0
    assert stage_profile.gc_pause_seconds >= 0.0


def test_start_operation_zero_overhead_when_flag_off(monkeypatch):
    """Flag off: no RSS/GC capture, no gc.callbacks registered, fields stay None."""
    monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    import gc as gc_module

    callbacks_before = list(gc_module.callbacks)
    with profiling.start_operation() as stage_profile:
        pass
    assert stage_profile.peak_rss_mb is None
    assert stage_profile.gc_collections is None
    # The GC pause-timer callback is never registered while the flag is off.
    assert list(gc_module.callbacks) == callbacks_before


def test_gc_callback_deregistered_after_operation(monkeypatch):
    """The temporary gc.callbacks pause timer is removed when the op ends."""
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    import gc as gc_module

    callbacks_before = list(gc_module.callbacks)
    with profiling.start_operation():
        # Inside the op the timer callback is registered.
        assert len(gc_module.callbacks) == len(callbacks_before) + 1
    assert list(gc_module.callbacks) == callbacks_before


def test_app_cpu_pct_degrades_to_none_without_psutil(monkeypatch):
    """psutil-absent path: app_cpu_pct is None, never a hard failure."""
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    monkeypatch.setattr(profiling, "_load_psutil_process", lambda: None)
    with profiling.start_operation() as stage_profile:
        pass
    assert stage_profile.app_cpu_pct is None


def test_to_dict_keys_match_harness_attribution_contract(monkeypatch):
    """Guard: the attribution keys emitted == the names the bench reads verbatim."""
    monkeypatch.setenv(PROFILE_ENV_VAR, "1")
    data = StageProfile().to_dict()
    assert _HARNESS_ATTRIBUTION_KEYS.issubset(set(data))
