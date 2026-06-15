"""Load-env-gated stage-timing collector for data-exchange (S89 Slice 2b).

The heavy-load harness (§2.2 of the S89 sprint) needs the *server's* view of
where an export/import spent its time — the client clock can only see total +
transport, never the split between DB time and Python serialisation time. This
module supplies exactly that, and **only when the load env flag is set**: in
production (`VBWD_DATA_EXCHANGE_PROFILE` unset) every public entry point is a
cheap no-op and the export/import response is byte-identical (Liskov: the
profile data is purely additive, never changes the contract).

How it works:

* :func:`profiling_enabled` reads the env flag once per call (cheap).
* :class:`StageProfile` accumulates per-operation DB seconds (split read /
  write / commit by the leading SQL verb), a query count, and named span
  seconds (serialise / deserialise) — all set to a fresh zero per operation.
* A SQLAlchemy ``before/after_cursor_execute`` hook attributes each statement's
  wall-clock to the *currently active* profile (a thread-local), so the route /
  CLI only has to open a profile span around the operation — it never threads a
  collector object through the exchanger contract.

NO OVERENGINEERING: no APM agent, no new infra, no always-on overhead. One env
flag, one thread-local, one SQLAlchemy event hook installed once at app boot
and inert while no profile is active.
"""
import gc
import logging
import os
import platform
import resource
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PROFILE_ENV_VAR = "VBWD_DATA_EXCHANGE_PROFILE"

# Named non-DB spans the exchanger / route wrap explicitly.
SPAN_SERIALISE = "serialise"
SPAN_DESERIALISE = "deserialise"

# Coarse statement classification by the leading SQL verb.
_READ_VERBS = ("SELECT", "WITH")
_COMMIT_VERBS = ("COMMIT", "BEGIN", "ROLLBACK", "SAVEPOINT", "RELEASE")

# ``resource.getrusage(...).ru_maxrss`` is in KILOBYTES on Linux but BYTES on
# macOS/BSD — normalise to MB per platform so ``peak_rss_mb`` is comparable.
_BYTES_PER_MB = 1024 * 1024
_KB_PER_MB = 1024
_MAXRSS_IS_KILOBYTES = platform.system() == "Linux"


def profiling_enabled() -> bool:
    """True only when the load env flag is set to a truthy value.

    Read fresh each call so a test can toggle the env var without re-importing.
    Production leaves the var unset, so this is ``False`` and the whole module
    is inert.
    """
    raw = os.environ.get(PROFILE_ENV_VAR, "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class StageProfile:
    """Accumulated stage timings for one export/import operation.

    All seconds are wall-clock. ``db_read`` / ``db_write`` / ``db_commit`` split
    the SQL time by the leading verb; ``query_count`` counts executed statements;
    ``spans`` holds the named non-DB spans (serialise / deserialise).
    """

    db_read_seconds: float = 0.0
    db_write_seconds: float = 0.0
    db_commit_seconds: float = 0.0
    query_count: int = 0
    spans: Dict[str, float] = field(default_factory=dict)

    # §2.2 attribution enrichment (S89 Slice 2b). All best-effort and load-gated:
    # captured only while ``VBWD_DATA_EXCHANGE_PROFILE`` is set and an operation is
    # active. ``None`` means "this env could not cheaply supply it" — never an
    # invented number. The field names match what the load harness reads verbatim
    # (``data_exchange_bench.py`` / ``data_exchange_runners.py``).
    peak_rss_mb: Optional[float] = None
    gc_collections: Optional[int] = None
    gc_pause_seconds: float = 0.0
    longest_txn_seconds: Optional[float] = None
    longest_lock_wait_seconds: Optional[float] = None
    app_cpu_pct: Optional[float] = None
    db_cpu_pct: Optional[float] = None
    table_bytes: Optional[int] = None
    index_bytes: Optional[int] = None

    @property
    def db_seconds(self) -> float:
        return self.db_read_seconds + self.db_write_seconds + self.db_commit_seconds

    def record_statement(self, statement: str, elapsed_seconds: float) -> None:
        """Attribute one executed SQL statement's elapsed time to a verb bucket."""
        self.query_count += 1
        verb = _leading_verb(statement)
        if verb in _COMMIT_VERBS:
            self.db_commit_seconds += elapsed_seconds
        elif verb in _READ_VERBS:
            self.db_read_seconds += elapsed_seconds
        else:
            self.db_write_seconds += elapsed_seconds

    def add_span(self, name: str, elapsed_seconds: float) -> None:
        self.spans[name] = self.spans.get(name, 0.0) + elapsed_seconds

    def to_dict(self) -> dict:
        """Serialise the split for the API ``_profile`` field / CLI line.

        With the load flag OFF this is byte-identical to the original contract
        (only the DB / serialise split) — the §2.2 attribution keys are appended
        ONLY when profiling is enabled (Liskov: purely additive, zero new keys in
        production). The added keys use the exact names the load harness reads.
        """
        result = {
            "query_count": self.query_count,
            "db_seconds": {
                "read": round(self.db_read_seconds, 6),
                "write": round(self.db_write_seconds, 6),
                "commit": round(self.db_commit_seconds, 6),
                "total": round(self.db_seconds, 6),
            },
            "serialise_seconds": round(self.spans.get(SPAN_SERIALISE, 0.0), 6),
            "deserialise_seconds": round(self.spans.get(SPAN_DESERIALISE, 0.0), 6),
        }
        if profiling_enabled():
            result.update(self._attribution_dict())
        return result

    def _attribution_dict(self) -> dict:
        """The §2.2 enrichment fields, named verbatim for the load harness."""
        return {
            "peak_rss_mb": _round_optional(self.peak_rss_mb, 3),
            "gc_collections": self.gc_collections,
            "gc_pause_seconds": round(self.gc_pause_seconds, 6),
            "longest_txn_seconds": _round_optional(self.longest_txn_seconds, 6),
            "longest_lock_wait_seconds": _round_optional(
                self.longest_lock_wait_seconds, 6
            ),
            "app_cpu_pct": _round_optional(self.app_cpu_pct, 2),
            "db_cpu_pct": _round_optional(self.db_cpu_pct, 2),
            "table_bytes": self.table_bytes,
            "index_bytes": self.index_bytes,
        }

    def server_timing_header(self) -> str:
        """Render the standard ``Server-Timing`` header value (milliseconds)."""
        parts = [
            f"db_read;dur={self.db_read_seconds * 1000:.3f}",
            f"db_write;dur={self.db_write_seconds * 1000:.3f}",
            f"db_commit;dur={self.db_commit_seconds * 1000:.3f}",
            f'queries;desc="count";dur={self.query_count}',
            f"serialise;dur={self.spans.get(SPAN_SERIALISE, 0.0) * 1000:.3f}",
            f"deserialise;dur={self.spans.get(SPAN_DESERIALISE, 0.0) * 1000:.3f}",
        ]
        return ", ".join(parts)


def _leading_verb(statement: str) -> str:
    """Return the upper-cased leading SQL keyword of ``statement`` (or '')."""
    stripped = statement.lstrip()
    if not stripped:
        return ""
    return stripped.split(None, 1)[0].upper()


def _round_optional(value: Optional[float], digits: int) -> Optional[float]:
    """Round ``value`` for serialisation, preserving ``None`` (best-effort)."""
    return None if value is None else round(value, digits)


def _maxrss_to_mb(maxrss: int) -> float:
    """Normalise ``getrusage(...).ru_maxrss`` to MB (KB on Linux, bytes elsewhere)."""
    if _MAXRSS_IS_KILOBYTES:
        return maxrss / _KB_PER_MB
    return maxrss / _BYTES_PER_MB


def _peak_rss_mb() -> float:
    """Current peak resident-set size of this process in MB (stdlib ``resource``)."""
    return _maxrss_to_mb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _gc_collection_total() -> int:
    """Total GC collection count across all generations (stdlib ``gc``)."""
    return sum(stat.get("collections", 0) for stat in gc.get_stats())


def _load_psutil_process() -> Any:
    """Return a ``psutil.Process`` for this process, or ``None`` if unavailable.

    psutil is NOT a hard dependency (S89 §2.2 best-effort stance): if it cannot
    be imported, CPU% degrades to ``None`` and we log once rather than fail. A
    seam so the absent-psutil path is unit-testable via monkeypatch.
    """
    try:
        import psutil
    except ImportError:
        logger.info("psutil unavailable; data-exchange app_cpu_pct will be None")
        return None
    return psutil.Process()


# Thread-local holder for the operation's active profile. ``None`` means no
# operation is being profiled on this thread, so the cursor hook does nothing.
_active = threading.local()


def _get_active_profile() -> Optional[StageProfile]:
    return getattr(_active, "profile", None)


def active_profile() -> Optional[StageProfile]:
    """Return the operation profile active on this thread, or ``None``.

    Public accessor (used by tests and any caller that wants to read the live
    collector without threading it through the exchanger contract).
    """
    return _get_active_profile()


class _ProfileSpan:
    """Context manager: activates a fresh :class:`StageProfile` for an operation.

    On enter it installs the profile on the thread-local (so the SQLAlchemy hook
    attributes statements to it); on exit it clears it. The caller reads the
    accumulated profile via the bound ``profile`` attribute. When profiling is
    disabled the profile is still created but the hook never fires (it checks
    the flag), so the totals stay zero and the caller can skip emitting them.

    When profiling IS enabled it also captures the §2.2 attribution dimensions
    around the operation: peak RSS, GC collection count + pause time (a temporary
    ``gc.callbacks`` timer registered only for the op's duration), app CPU%
    (best-effort via psutil), and — when a ``session`` / ``table_name`` is given —
    the op-end Postgres catalog figures (longest transaction / lock-wait, table +
    index size). With the flag off NONE of this runs (zero overhead, Liskov).
    """

    def __init__(
        self, *, table_name: Optional[str] = None, session: Any = None
    ) -> None:
        self.profile = StageProfile()
        self._table_name = table_name
        self._session = session
        self._capture = profiling_enabled()
        self._gc_callback: Optional[Any] = None
        self._gc_collections_start = 0
        self._psutil_process: Any = None

    def __enter__(self) -> StageProfile:
        _active.profile = self.profile
        if self._capture:
            self._begin_capture()
        return self.profile

    def __exit__(self, *_exc: Any) -> None:
        # Detach the profile from the thread-local FIRST so the profiler's own
        # op-end catalog probes are not attributed to the operation's query_count
        # / db_seconds (they would otherwise self-inflate the attribution).
        _active.profile = None
        if self._capture:
            self._end_capture()

    def _begin_capture(self) -> None:
        """Snapshot baselines + arm the GC pause timer (flag-on only)."""
        self._gc_collections_start = _gc_collection_total()
        self._gc_callback = _make_gc_pause_callback(self.profile)
        gc.callbacks.append(self._gc_callback)
        self._psutil_process = _load_psutil_process()
        if self._psutil_process is not None:
            # Prime the psutil interval so the op-end read is a true delta.
            self._psutil_process.cpu_percent(None)

    def _end_capture(self) -> None:
        """Compute deltas, run the cheap catalog queries, deregister the timer."""
        self.profile.peak_rss_mb = _peak_rss_mb()
        self.profile.gc_collections = (
            _gc_collection_total() - self._gc_collections_start
        )
        if self._gc_callback is not None and self._gc_callback in gc.callbacks:
            gc.callbacks.remove(self._gc_callback)
        if self._psutil_process is not None:
            self.profile.app_cpu_pct = self._psutil_process.cpu_percent(None)
        if self._session is not None:
            _sample_pg_activity(self._session, self.profile)
        if self._session is not None and self._table_name is not None:
            _sample_table_sizes(self._session, self._table_name, self.profile)


def start_operation(
    *, table_name: Optional[str] = None, session: Any = None
) -> _ProfileSpan:
    """Begin profiling one export/import operation (use as a context manager).

    ``table_name`` (the exchanger's model ``__tablename__``) and ``session`` are
    optional: when both are supplied the op-end catalog queries size that table +
    its indexes; ``session`` alone still samples ``pg_stat_activity``. Both are
    best-effort and only consulted while the load flag is set.
    """
    return _ProfileSpan(table_name=table_name, session=session)


def _make_gc_pause_callback(profile: StageProfile):
    """A ``gc.callbacks`` entry that accumulates GC pause wall-clock into profile.

    The CPython contract fires the callback with ``phase`` ``"start"`` then
    ``"stop"`` around each collection; the wall-clock between the two is the pause.
    """
    timer = {"start": 0.0}

    def _on_gc(phase: str, _info: dict) -> None:
        if phase == "start":
            timer["start"] = time.perf_counter()
        elif phase == "stop" and timer["start"]:
            profile.gc_pause_seconds += time.perf_counter() - timer["start"]
            timer["start"] = 0.0

    return _on_gc


def _probe(session: Any, query: Any, params: Optional[dict], label: str) -> Any:
    """Run a best-effort catalog probe inside a SAVEPOINT.

    A failure (non-Postgres engine, missing catalog/extension) is rolled back to
    the savepoint so the caller's transaction is NOT poisoned, then logged and
    reported as ``None`` — never raised into the data-exchange operation.
    """
    try:
        with session.begin_nested():
            return session.execute(query, params or {}).first()
    except Exception as exc:  # pragma: no cover - non-PG / catalog-absent path
        logger.info("data-exchange profile probe %s skipped: %s", label, exc)
        return None


def _sample_pg_activity(session: Any, profile: StageProfile) -> None:
    """Best-effort: longest open transaction + longest lock-wait for this backend.

    Reads ``pg_stat_activity`` for the current backend PID at op end. Lock-wait is
    the time in the current state when the backend is blocked on a ``Lock`` event
    (a ``CASE`` — ``FILTER`` is aggregate-only), else 0.
    """
    from sqlalchemy import text

    query = text(
        "SELECT "
        "COALESCE(EXTRACT(EPOCH FROM (now() - xact_start)), 0) AS txn_seconds, "
        "CASE WHEN wait_event_type = 'Lock' "
        "  THEN COALESCE(EXTRACT(EPOCH FROM (now() - state_change)), 0) "
        "  ELSE 0 END AS lock_wait_seconds "
        "FROM pg_stat_activity WHERE pid = pg_backend_pid()"
    )
    row = _probe(session, query, None, "pg_stat_activity")
    if row is None:
        return
    profile.longest_txn_seconds = float(row.txn_seconds or 0.0)
    profile.longest_lock_wait_seconds = float(row.lock_wait_seconds or 0.0)


def _sample_table_sizes(session: Any, table_name: str, profile: StageProfile) -> None:
    """Best-effort: ``pg_total_relation_size`` + ``pg_indexes_size`` for the table.

    Sized at op end via ``to_regclass`` so a missing/relocated table degrades to
    ``None`` rather than raising.
    """
    from sqlalchemy import text

    query = text(
        "SELECT "
        "pg_total_relation_size(to_regclass(:table)) AS table_bytes, "
        "pg_indexes_size(to_regclass(:table)) AS index_bytes"
    )
    row = _probe(session, query, {"table": table_name}, f"table-size({table_name})")
    if row is None:
        return
    profile.table_bytes = int(row.table_bytes) if row.table_bytes is not None else None
    profile.index_bytes = int(row.index_bytes) if row.index_bytes is not None else None


class _NamedSpan:
    """Time a named non-DB span (serialise/deserialise) into the active profile."""

    def __init__(self, name: str, profile: StageProfile) -> None:
        self._name = name
        self._profile = profile
        self._start = 0.0

    def __enter__(self) -> "_NamedSpan":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._profile.add_span(self._name, time.perf_counter() - self._start)


class _NoOpSpan:
    """Zero-overhead span used when profiling is off / no operation is active.

    Shared singleton so wrapping a per-row span in production allocates nothing
    and reads no clock — the wrapped code runs exactly as before (DoD: zero
    overhead with the flag off).
    """

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


_NO_OP_SPAN = _NoOpSpan()


def span(name: str):
    """Wrap a serialise/deserialise span; attributes its time to the profile.

    Returns a shared no-op context manager (no clock read, no allocation cost
    beyond the call) unless profiling is enabled AND an operation is active, so
    wrapping a hot per-row loop is safe in production.
    """
    profile = _get_active_profile()
    if profile is None or not profiling_enabled():
        return _NO_OP_SPAN
    return _NamedSpan(name, profile)


def install_cursor_timing(engine: Any) -> None:
    """Install the load-gated ``before/after_cursor_execute`` timing hook once.

    Called at app boot for the SQLAlchemy engine. The hook is always registered
    but does nothing unless (a) the load env flag is set AND (b) an operation
    span is active on the current thread — so production pays only a cheap flag
    read per statement, and only while a data-exchange operation is running.
    """
    from sqlalchemy import event

    if getattr(engine, "_vbwd_data_exchange_timing_installed", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, _cursor, _statement, _params, context, _executemany):
        if not profiling_enabled() or _get_active_profile() is None:
            return
        context._vbwd_query_start = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, _cursor, statement, _params, context, _executemany):
        profile = _get_active_profile()
        if profile is None or not profiling_enabled():
            return
        started = getattr(context, "_vbwd_query_start", None)
        if started is None:
            return
        profile.record_statement(statement, time.perf_counter() - started)

    engine._vbwd_data_exchange_timing_installed = True
