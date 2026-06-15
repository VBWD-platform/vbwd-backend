"""Shared integration-test database hygiene helpers.

Tests must clean up after themselves and MUST NOT wipe the database — no
``TRUNCATE``-all, no ``DROP SCHEMA``. Many plugin integration suites share a
single ``*_test`` database, so a wipe-based isolation in one suite poisons every
other suite running in the same ``bin/pre-commit-check.sh --full`` session (a
sibling's ``drop_all()`` strands ENUM types or removes a shared table another
suite still needs).

Instead, the schema is built **once per process** with
``create_all(checkfirst=True)`` (never dropped), canonical baseline rows are
committed once, and each test runs inside a transaction that is **rolled back**
at teardown — the rollback IS the cleanup, nothing the test writes ever persists.
This is also far faster than per-test ``TRUNCATE`` of the whole catalog. Core
test infrastructure — agnostic, imports no plugin.
"""
from contextlib import contextmanager

from sqlalchemy import inspect

# ---------------------------------------------------------------------------
# Self-cleaning isolation (no DB wipe) — the supported approach.
#
# Tests must clean up after themselves and MUST NOT wipe the database (no
# ``TRUNCATE``-all, no ``DROP SCHEMA``). Each test runs inside a transaction
# bound to a single connection; at teardown the transaction is rolled back, so
# nothing the test wrote ever persists — the rollback IS the cleanup. The schema
# is built once per process with ``create_all(checkfirst=True)`` (never dropped),
# and canonical baseline reference rows (RBAC roles) are committed once.
#
# Flask-SQLAlchemy 3.1's ``Session.get_bind`` returns ``engines[None]`` (the
# default engine) before honouring a session-level bind, so we join the external
# transaction by temporarily pointing ``engines[None]`` at the live connection
# and putting the scoped session in ``create_savepoint`` mode (a service-level
# ``commit()`` inside the test becomes a SAVEPOINT release, so the test sees its
# own writes while the outer transaction stays open to roll back).
# ---------------------------------------------------------------------------


def ensure_schema_and_baseline(db):
    """Build any missing tables and commit canonical baseline rows (idempotent).

    Many plugin integration suites share ONE ``*_test`` database in a single
    ``bin/pre-commit-check.sh --full`` process, all using the same
    ``vbwd.extensions.db`` instance. Each suite's session-scoped ``app`` fixture
    imports its own models (registering more tables in ``db.metadata``) and then
    calls this helper. We therefore must run ``create_all`` on EVERY call, not
    just the first: a one-shot per-process guard would build only the tables the
    first suite to run had registered, leaving every later suite's tables
    missing (``relation "..." does not exist``).

    ``create_all`` uses ``checkfirst=True`` (the SQLAlchemy default), so it only
    emits DDL for tables that do not yet exist — it never drops or wipes data and
    is cheap to call repeatedly. Commits the canonical RBAC role rows (idempotent
    — guarded on existing rows) so any ``User`` created inside a test's
    rolled-back transaction satisfies its role FK. The caller must have imported
    every model whose table should exist before calling.
    """
    db.create_all()
    _seed_canonical_rbac(db)


def _seed_canonical_rbac(db) -> None:
    """Commit the canonical RBAC role rows once if absent (idempotent)."""
    table_names = inspect(db.engine).get_table_names(schema="public")
    if "vbwd_user_role" not in table_names:
        return
    from vbwd.models.user_role import RoleDefinition, canonical_role_rows

    if db.session.query(RoleDefinition).first() is not None:
        db.session.remove()
        return
    from sqlalchemy import insert

    db.session.execute(insert(RoleDefinition.__table__), canonical_role_rows())
    db.session.commit()
    db.session.remove()


@contextmanager
def rollback_isolation(db):
    """Run a test in a transaction that is rolled back on teardown.

    The test sees its own writes (even after a service-level ``commit()``), but
    nothing persists past the test — self-cleaning, no wipe. Restores the real
    engine binding afterwards so the next test starts clean.
    """
    engines = db.engines
    real_engine = engines[None]
    connection = real_engine.connect()
    transaction = connection.begin()
    engines[None] = connection
    db.session.remove()
    db.session.configure(join_transaction_mode="create_savepoint")
    try:
        yield db
    finally:
        # Restore the real engine binding NO MATTER WHAT — a failure while
        # rolling back or closing the connection must not leave ``engines[None]``
        # pointing at a dead Connection, which would break every later test in
        # the process (``db.engine`` would no longer be an Engine).
        try:
            db.session.remove()
        finally:
            try:
                transaction.rollback()
            finally:
                try:
                    connection.close()
                finally:
                    engines[None] = real_engine
