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
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

PROFILE_ENV_VAR = "VBWD_DATA_EXCHANGE_PROFILE"

# Named non-DB spans the exchanger / route wrap explicitly.
SPAN_SERIALISE = "serialise"
SPAN_DESERIALISE = "deserialise"

# Coarse statement classification by the leading SQL verb.
_READ_VERBS = ("SELECT", "WITH")
_COMMIT_VERBS = ("COMMIT", "BEGIN", "ROLLBACK", "SAVEPOINT", "RELEASE")


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
        """Serialise the split for the API ``_profile`` field / CLI line."""
        return {
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
    """

    def __init__(self) -> None:
        self.profile = StageProfile()

    def __enter__(self) -> StageProfile:
        _active.profile = self.profile
        return self.profile

    def __exit__(self, *_exc: Any) -> None:
        _active.profile = None


def start_operation() -> _ProfileSpan:
    """Begin profiling one export/import operation (use as a context manager)."""
    return _ProfileSpan()


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
