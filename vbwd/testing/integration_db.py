"""Shared integration-test database hygiene helpers.

Many plugin integration suites share a single ``*_test`` database. The old
per-test ``create_all()`` / ``drop_all()`` pattern strands state when several
suites run together (the whole-backend ``bin/pre-commit-check.sh --full`` run):

  1. ``MetaData.drop_all()`` drops tables but **not** standalone PostgreSQL
     ``ENUM`` types, so a later ``create_all()`` — in the same suite or another
     plugin's — fails with ``CREATE TYPE userstatus ... already exists``
     (``duplicate key ... pg_type_typname_nsp_index``).
  2. A sibling suite's ``drop_all()`` removes a shared table another suite still
     needs, so its seeder fails with ``relation "vbwd_user" does not exist``.

These helpers reset the schema **once per session** (dropping tables *and*
enums by recreating the ``public`` schema) and isolate each test by
``TRUNCATE``, mirroring the cms suite's proven approach. Core test
infrastructure — agnostic, imports no plugin.
"""
from sqlalchemy import inspect, text


def reset_schema_and_create_all(db):
    """Drop the ``public`` schema (tables + ENUM types) and rebuild it once.

    Runs the DROP/CREATE and ``create_all()`` on a single fresh connection so
    ``create_all()``'s ``checkfirst`` reflection sees the just-cleared catalog
    (a separate pooled connection can carry a pre-DROP snapshot and then
    duplicate/skip objects). The caller must have imported every model whose
    table should exist before calling this.

    Under the whole-suite gate several plugin suites share one ``*_test`` DB and
    each calls this from its own session-scoped ``app`` fixture. A sibling
    suite's pooled connection can sit idle-in-transaction holding an
    ``AccessShareLock`` on the ``public`` namespace, which deadlocks this
    ``DROP SCHEMA`` (it needs ``AccessExclusiveLock``). A test-DB reset
    legitimately owns the whole database, so we first terminate every *other*
    backend on it, then guard the DROP with a short ``lock_timeout`` so it fails
    fast and retries rather than blocking forever.
    """
    db.session.remove()
    _terminate_other_backends(db)
    with db.engine.connect() as connection:
        connection.execute(text("SET lock_timeout = '30s'"))
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.commit()
        db.metadata.create_all(bind=connection)
        connection.commit()


def _terminate_other_backends(db):
    """Close every other connection to this database before a schema reset.

    Idle pooled connections from sibling suites' session-scoped engines (still
    alive for the whole pytest session) can hold namespace locks that deadlock
    ``DROP SCHEMA``. ``pg_terminate_backend`` returns those connections to a
    clean state; SQLAlchemy transparently re-opens them when next used.
    """
    with db.engine.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        connection.commit()


def truncate_all_tables(db):
    """Clear data from every existing table without touching the schema.

    Runs on its own short-lived autocommit-scoped connection (``engine.begin``)
    rather than ``db.session`` so it cannot deadlock against a transaction a
    prior test left open. Truncating on SETUP is robust against a prior test
    that left rows behind.
    """
    db.session.remove()
    table_names = inspect(db.engine).get_table_names(schema="public")
    if not table_names:
        return
    quoted = ", ".join(f'public."{name}"' for name in table_names)
    with db.engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
        # Re-seed the canonical RBAC role rows the TRUNCATE wiped, so any User
        # created afterwards (the test-data seeder's admin, or a test fixture)
        # does not violate the ``vbwd_user.role`` FK to ``vbwd_user_role``.
        # Through the model catalog, never raw DDL.
        if "vbwd_user_role" in table_names:
            from sqlalchemy import insert

            from vbwd.models.user_role import RoleDefinition, canonical_role_rows

            connection.execute(insert(RoleDefinition.__table__), canonical_role_rows())
