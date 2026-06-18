"""Repo-wide pytest hooks.

Connection-leak guard
---------------------
Most test suites here build their own Flask app per test (or per module), and
each app gets its own SQLAlchemy engine with a connection pool. Those engines
are almost never disposed, so their pooled connections linger and accumulate
across a full-suite run until PostgreSQL refuses new ones
("FATAL: sorry, too many clients already") and every later test errors at setup.

We track every engine the moment it opens a connection (cheap, via a global
SQLAlchemy event) and dispose them after each test, returning pooled connections
to the server. Pooling still works *within* a test (individual tests stay fast),
but connections can't pile up *between* tests — the full suite stays well under
``max_connections``.
"""
import weakref

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

_engines: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def pytest_configure(config):
    """Register the shared ``no_db_isolation`` marker once for the whole repo.

    Plugin integration suites isolate each test in a rolled-back transaction
    (``vbwd/testing/integration_db.rollback_isolation``), which binds the scoped
    session to one connection and rolls it back. A test marked
    ``no_db_isolation`` runs WITHOUT that wrapper — it needs a real
    ``db.engine`` (e.g. a migration test that opens its OWN connection and rolls
    back itself, or a race spec that contends across genuinely separate
    connections) and is responsible for cleaning up anything it commits.
    """
    config.addinivalue_line(
        "markers",
        "no_db_isolation: run without the rolled-back-transaction isolation "
        "(the test manages its own connection/cleanup).",
    )


@event.listens_for(Engine, "engine_connect")
def _remember_engine(connection, *args):
    """Record each engine as it hands out a connection."""
    engine = getattr(connection, "engine", None)
    if engine is not None:
        _engines.add(engine)


@pytest.fixture(autouse=True)
def _dispose_sqlalchemy_engines():
    """Release each test's DB resources afterwards.

    First close the shared scoped session — an uncommitted session left "idle in
    transaction" keeps table locks, which later deadlocks another test's
    ``db.drop_all()`` (``DROP TABLE`` blocks on the lock forever). Then dispose
    the engines so their pooled connections return to the server.

    Also reset the global Flask-Limiter window BEFORE each test. The limiter is a
    process-wide singleton backed by a shared (Redis) store that ``init_app``
    does not swap for the test config's ``memory://``, so per-route windows like
    ``/auth/login`` ("30 per minute") otherwise accumulate across every test in
    the run (and across runs, since the store is never flushed) until later
    logins 429. A clean window per test makes the suite deterministic; the
    dedicated rate-limit specs are self-contained within one test, so they are
    unaffected.
    """
    try:
        from vbwd.extensions import limiter

        limiter.reset()
    except Exception:
        # Best-effort: a limiter that cannot reset must never fail a test.
        pass
    yield
    try:
        from vbwd.extensions import db

        db.session.remove()
    except Exception:
        pass
    for engine in list(_engines):
        try:
            engine.dispose()
        except Exception:
            # A best-effort cleanup must never fail a test.
            pass
    _engines.clear()
