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
    """
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
